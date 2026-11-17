from odoo import api, fields, models

from ..rules import CHANNELS, VISITS


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    bekvam_visit_type = fields.Selection(
        VISITS + [("historical_unknown", "Sin clasificacion historica"),
                  ("unattributed", "Devolucion sin atribucion")],
        compute="_compute_bekvam_origin", store=True, index=True,
    )
    bekvam_discovery_channel = fields.Selection(CHANNELS, compute="_compute_bekvam_origin", store=True, index=True)
    bekvam_attributed_config_id = fields.Many2one("pos.config", compute="_compute_bekvam_origin", store=True, index=True)
    bekvam_in_scope = fields.Boolean(compute="_compute_bekvam_origin", store=True, index=True)
    bekvam_currency_id = fields.Many2one(related="order_id.currency_id", string="Moneda del reporte", store=True)

    @api.depends("qty", "refunded_orderline_id", "order_id.config_id.bekvam_origin_scope",
                 "order_id.bekvam_visit_type", "order_id.bekvam_discovery_channel",
                 "refunded_orderline_id.order_id.config_id.bekvam_origin_scope",
                 "refunded_orderline_id.order_id.bekvam_visit_type",
                 "refunded_orderline_id.order_id.bekvam_discovery_channel")
    def _compute_bekvam_origin(self):
        for line in self:
            source = line.refunded_orderline_id.order_id if line.qty < 0 and line.refunded_orderline_id else line.order_id
            line.bekvam_attributed_config_id = source.config_id
            line.bekvam_in_scope = source.config_id.bekvam_origin_scope
            # An unlinked negative line is never given an invented channel.
            attributable = line.qty >= 0 or bool(line.refunded_orderline_id)
            line.bekvam_visit_type = (source.bekvam_visit_type or "historical_unknown") if attributable else "unattributed"
            line.bekvam_discovery_channel = source.bekvam_discovery_channel if attributable else False
