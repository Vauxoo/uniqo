"""Odoo integration tests. Require the complete Odoo.sh dependency graph."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "bekvam_origin")
class TestBekvamOrigin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Transactional copies of the configured staging fixtures avoid the standard
        # accounting helper's skip when the administrator's default company has no chart.
        source = cls.env["pos.config"].search([("name", "ilike", "UN01")], limit=1)
        if not source:
            raise AssertionError("Prepare la configuracion de staging UN01 antes de ejecutar esta suite.")
        cls.env = source.with_company(source.company_id).env
        cls.basic_config = source.copy({"name": "QA origen UN01"})
        cls.other_currency_config = source.copy({"name": "QA origen UN02", "bekvam_origin_scope": False})
        for configuration in (cls.basic_config, cls.other_currency_config):
            configuration.sequence_id = cls.env["ir.sequence"].create({
                "name": "QA origen numeracion aislada", "implementation": "no_gap",
                "prefix": "QA-BK/", "padding": 5, "company_id": source.company_id.id,
            })
        cls.customer = cls.env["res.partner"].search([("name", "=", "PRUEBA TPV ORIGEN 20261027")], limit=1)
        if not cls.customer:
            raise AssertionError("Falta el cliente ficticio PRUEBA TPV ORIGEN 20261027 del staging.")
        cls.basic_config.write({"bekvam_origin_scope": True,
                                "bekvam_origin_required_from": fields.Datetime.now() - timedelta(days=1)})
        cls.session = cls.env["pos.session"].create({"config_id": cls.basic_config.id, "user_id": cls.env.uid})
        cls.service = cls.env["product.product"].create({
            "name": "QA origen montaje", "type": "service", "available_in_pos": True,
            "list_price": 10, "taxes_id": [(5, 0, 0)],
        })

    def make_order(self, visit=False, channel=False, qty=1, original=None, state="paid", config=None):
        session = self.session
        if config:
            session = self.env["pos.session"].create({"config_id": config.id, "user_id": self.env.uid})
        order = self.env["pos.order"].create({
            "session_id": session.id, "partner_id": self.customer.id,
            "pricelist_id": session.config_id.pricelist_id.id,
            "amount_total": qty * 10, "amount_tax": 0, "amount_paid": qty * 10, "amount_return": 0,
            "state": "draft", "bekvam_visit_type": visit, "bekvam_discovery_channel": channel,
            "lines": [(0, 0, {"product_id": self.service.id, "qty": qty, "price_unit": 10,
                              "price_subtotal": qty * 10, "price_subtotal_incl": qty * 10,
                              "refunded_orderline_id": original.id if original else False})],
        })
        if state != "draft":
            order.write({"state": state})
        return order

    def test_required_before_any_processing(self):
        before = self.env["pos.order"].search_count([])
        packet = {"data": {"pos_session_id": self.session.id, "partner_id": self.customer.id,
                           "lines": [(0, 0, {"qty": 1})]}}
        with self.assertRaises(ValidationError):
            self.env["pos.order"]._process_order(packet, False, False)
        self.assertEqual(self.env["pos.order"].search_count([]), before)

    def test_first_visit_needs_channel(self):
        with self.assertRaises(ValidationError):
            self.make_order("first_visit")
        for channel in ("facebook", "instagram", "tiktok", "google", "referral", "mall"):
            self.assertEqual(self.make_order("first_visit", channel).bekvam_discovery_channel, channel)

    def test_previous_visit_rejects_channel(self):
        with self.assertRaises(ValidationError):
            self.make_order("previous_visit", "facebook")
        self.assertFalse(self.make_order("previous_visit").bekvam_discovery_channel)

    def test_draft_can_be_incomplete_and_finalization_is_blocked(self):
        order = self.make_order("first_visit", state="draft")
        with self.assertRaises(ValidationError):
            order.write({"state": "paid"})
        self.assertEqual(order.state, "draft")
        order.write({"bekvam_discovery_channel": "google", "state": "paid"})
        with self.assertRaises(ValidationError):
            order.write({"bekvam_visit_type": "previous_visit", "bekvam_discovery_channel": False})

    def test_service_refund_uses_original_classification(self):
        sale = self.make_order("first_visit", "instagram")
        refund = self.make_order(qty=-1, original=sale.lines)
        self.assertEqual(refund.lines.bekvam_discovery_channel, "instagram")
        self.assertEqual(refund.lines.bekvam_attributed_config_id, self.basic_config)
        self.assertAlmostEqual(sale.lines.price_subtotal + refund.lines.price_subtotal, 0)

    def test_unscoped_sale_and_empty_abono(self):
        self.assertFalse(self.make_order(config=self.other_currency_config).bekvam_visit_type)
        abono = self.make_order(qty=0, state="draft")
        abono.lines.unlink()
        abono.write({"state": "paid"})
        self.assertFalse(abono.bekvam_visit_type)

    def test_cancelled_order_not_in_report(self):
        order = self.make_order(state="draft")
        order.write({"state": "cancel"})
        action = self.env.ref("bekvam_pos_visit_origin.origin_report_action")
        self.assertFalse(self.env["pos.order.line"].search(
            [("order_id", "=", order.id), ("state", "in", ["paid", "done", "invoiced"])]))
        self.assertIn("bekvam_in_scope", action.domain)

    def test_anonymous_request_is_rejected_even_with_complete_answer(self):
        with self.assertRaises(ValidationError):
            self.env["pos.order"].bekvam_validate_origin({
                "pos_session_id": self.session.id, "partner_id": False,
                "bekvam_visit_type": "first_visit", "bekvam_discovery_channel": "google",
                "lines": [(0, 0, {"qty": 1})],
            })

    def test_historical_sale_stays_unclassified(self):
        self.basic_config.write({"bekvam_origin_required_from": False})
        historical = self.make_order()
        self.basic_config.write({"bekvam_origin_required_from": fields.Datetime.now() - timedelta(hours=1)})
        self.assertFalse(historical.bekvam_visit_type)
        self.assertEqual(historical.lines.bekvam_visit_type, "historical_unknown")

    def test_refund_in_other_branch_keeps_original_attribution(self):
        original = self.make_order("first_visit", "facebook")
        refund = self.make_order(qty=-1, original=original.lines, config=self.other_currency_config)
        self.assertEqual(refund.lines.bekvam_attributed_config_id, self.basic_config)
        self.assertEqual(refund.lines.pos_config_id, self.other_currency_config)
        self.assertEqual(refund.lines.bekvam_discovery_channel, "facebook")

    def test_report_keeps_sales_and_refunds_as_separate_lines(self):
        original = self.make_order("first_visit", "mall")
        self.make_order(qty=-1, original=original.lines)
        lines = self.env["pos.order.line"].search([
            ("order_id", "in", [original.id] + original.lines.refund_orderline_ids.order_id.ids),
            ("bekvam_in_scope", "=", True), ("state", "in", ["paid", "done", "invoiced"]),
        ])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(sum(lines.mapped("price_subtotal")), 0)

    def test_two_scoped_branches_consolidate_without_duplicate_sales(self):
        self.other_currency_config.write({"bekvam_origin_scope": True,
            "bekvam_origin_required_from": fields.Datetime.now() - timedelta(days=1)})
        first = self.make_order("first_visit", "google")
        previous = self.make_order("previous_visit", config=self.other_currency_config)
        groups = self.env["pos.order.line"].read_group(
            [("order_id", "in", (first | previous).ids), ("bekvam_in_scope", "=", True),
             ("state", "in", ["paid", "done", "invoiced"])],
            ["price_subtotal:sum"], ["bekvam_attributed_config_id"])
        self.assertEqual(len(groups), 2)
        self.assertEqual(sum(group["price_subtotal"] for group in groups), 20)

    def test_acknowledgement_recovery_is_read_only_and_rejects_changes(self):
        order = self.make_order("first_visit", "instagram")
        order.write({"pos_reference": "QA-BK-recovery-unique"})
        packet = {"name": order.pos_reference, "pos_session_id": self.session.id,
            "partner_id": self.customer.id, "bekvam_visit_type": "first_visit",
            "bekvam_discovery_channel": "instagram", "statement_ids": [],
            "lines": [(0, 0, {"product_id": self.service.id, "qty": 1,
                               "price_unit": 10, "discount": 0})]}
        before = self.env["pos.order"].search_count([])
        for _retry in range(2):
            result = self.env["pos.order"].bekvam_recover_origin_order(packet)
            self.assertEqual(result[0]["id"], order.id)
        self.assertEqual(self.env["pos.order"].search_count([]), before)
        packet["bekvam_discovery_channel"] = "facebook"
        with self.assertRaises(UserError):
            self.env["pos.order"].bekvam_recover_origin_order(packet)
