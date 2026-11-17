import json

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..rules import CHANNELS, FINAL_STATES, VISITS, has_new_purchase, pair_error, ui_lines


class PosOrder(models.Model):
    _inherit = "pos.order"

    bekvam_visit_type = fields.Selection(VISITS, string="Tipo de visita", copy=False, index=True)
    bekvam_discovery_channel = fields.Selection(CHANNELS, string="Origen declarado", copy=False, index=True)

    @api.model
    def _bekvam_active(self, config):
        return bool(config.bekvam_origin_scope and config.bekvam_origin_required_from
                    and fields.Datetime.now() >= config.bekvam_origin_required_from)

    @api.model
    def _bekvam_session(self, data):
        session = self.env["pos.session"].browse(int(data.get("pos_session_id") or 0)).exists()
        if not session or session.company_id not in self.env.companies:
            raise UserError("No se puede verificar la sesion del TPV.")
        session.check_access_rights("read")
        session.check_access_rule("read")
        return session

    @api.model
    def bekvam_validate_origin(self, data):
        """Read-only preflight. The processing path repeats this authoritative check."""
        config = self._bekvam_session(data).config_id
        try:
            lines = ui_lines(data.get("lines"))
        except (TypeError, ValueError) as error:
            raise UserError(str(error)) from error
        required = self._bekvam_active(config) and has_new_purchase(lines)
        error = pair_error(data.get("bekvam_visit_type"), data.get("bekvam_discovery_channel"), required)
        if error:
            raise ValidationError(error)
        if required:
            partner_id = int(data.get("partner_id") or 0)
            if not partner_id or partner_id == config.bekvam_default_partner_id.id:
                raise ValidationError("Seleccione un cliente identificado; Consumidor Final no cumple esta regla.")
        return True

    @api.model
    def _order_fields(self, ui_order):
        values = super()._order_fields(ui_order)
        values.update({name: ui_order.get(name) or False for name in
                       ("bekvam_visit_type", "bekvam_discovery_channel")})
        return values

    def _get_fields_for_draft_order(self):
        return list(dict.fromkeys(super()._get_fields_for_draft_order() +
                                 ["bekvam_visit_type", "bekvam_discovery_channel"]))

    def _export_for_ui(self, order):
        result = super()._export_for_ui(order)
        result.update(bekvam_visit_type=order.bekvam_visit_type,
                      bekvam_discovery_channel=order.bekvam_discovery_channel)
        return result

    @api.model
    def _process_order(self, order, draft, existing_order):
        data = order["data"]
        if not draft:
            self.bekvam_validate_origin(data)
        # Roll back all effects if a parent swallowed a failure in action_pos_order_paid.
        with self.env.cr.savepoint():
            order_id = super()._process_order(order, draft, existing_order)
            record = self.browse(order_id)
            if not draft and self._bekvam_active(record.config_id) and record.lines:
                if record.state not in FINAL_STATES:
                    raise ValidationError("La venta no fue finalizada. Corrija el error antes de reintentar.")
                record._bekvam_check_required()
            return order_id

    def _bekvam_check_required(self):
        for record in self:
            required = (self._bekvam_active(record.config_id)
                        and any(line.qty > 0 for line in record.lines))
            error = pair_error(record.bekvam_visit_type, record.bekvam_discovery_channel, required)
            if error:
                raise ValidationError(error)
            if required and (not record.partner_id
                             or record.partner_id == record.config_id.bekvam_default_partner_id):
                raise ValidationError("La compra requiere un cliente identificado.")

    @api.constrains("bekvam_visit_type", "bekvam_discovery_channel")
    def _bekvam_check_pair(self):
        for record in self:
            error = pair_error(record.bekvam_visit_type, record.bekvam_discovery_channel)
            if error:
                raise ValidationError(error)

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            records.filtered(lambda order: order.state in FINAL_STATES)._bekvam_check_required()
            return records

    def write(self, values):
        origin_fields = {"bekvam_visit_type", "bekvam_discovery_channel"}
        for record in self.filtered(lambda order: order.state in FINAL_STATES):
            if any((values[name] or False) != record[name]
                   for name in origin_fields.intersection(values)):
                raise ValidationError("La respuesta historica de una venta finalizada no puede modificarse.")
        transitioning = self.filtered(lambda order: order.state not in FINAL_STATES)
        with self.env.cr.savepoint():
            result = super().write(values)
            if values.get("state") in FINAL_STATES:
                transitioning._bekvam_check_required()
            return result

    @api.model
    def _bekvam_fingerprint(self, data):
        """Canonical commercial/payment snapshot used for acknowledgement-loss recovery."""
        lines = sorted((
            int(line.get("product_id") or 0), round(float(line.get("qty") or 0), 8),
            round(float(line.get("price_unit") or 0), 8), round(float(line.get("discount") or 0), 8),
            int(line.get("refunded_orderline_id") or 0),
        ) for line in ui_lines(data.get("lines")))
        payments = sorted((int(command[2]["payment_method_id"]), round(float(command[2]["amount"]), 8))
                          for command in data.get("statement_ids", []) if float(command[2]["amount"]))
        return json.dumps([lines, payments, int(data.get("partner_id") or 0),
                           data.get("bekvam_visit_type") or False,
                           data.get("bekvam_discovery_channel") or False], sort_keys=True)

    @api.model
    def bekvam_recover_origin_order(self, data):
        """Never creates a sale. It distinguishes an acknowledged retry from a new sale."""
        session = self._bekvam_session(data)
        self.check_access_rights("read")
        orders = self.search([
            ("company_id", "=", session.company_id.id),
            ("config_id", "=", session.config_id.id),
            ("pos_reference", "=", data.get("name")),
            ("state", "in", list(FINAL_STATES)),
        ], limit=2)
        if not orders:
            return []
        if len(orders) != 1:
            raise UserError("Hay varias operaciones con esta referencia. Revise antes de reintentar.")
        record = orders[0]
        snapshot = {
            "partner_id": record.partner_id.id,
            "bekvam_visit_type": record.bekvam_visit_type,
            "bekvam_discovery_channel": record.bekvam_discovery_channel,
            "lines": [(0, 0, {"product_id": line.product_id.id, "qty": line.qty,
                              "price_unit": line.price_unit, "discount": line.discount,
                              "refunded_orderline_id": line.refunded_orderline_id.id}) for line in record.lines],
            "statement_ids": [(0, 0, {"payment_method_id": payment.payment_method_id.id,
                                      "amount": payment.amount}) for payment in record.payment_ids],
        }
        if self._bekvam_fingerprint(data) != self._bekvam_fingerprint(snapshot):
            raise UserError("La venta ya existe con datos distintos. No se reenviara ni cobrara de nuevo.")
        return [{"id": record.id, "pos_reference": record.pos_reference,
                 "account_move": record.account_move.id}]
