from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    bekvam_origin_scope = fields.Boolean(
        string="Sucursal fisica incluida en origen", default=False,
        help="Activar solo en UN01 y UN02. No activar en WhatsApp ni comercio electronico.",
    )
    bekvam_origin_required_from = fields.Datetime(
        string="Exigir primera visita desde",
        help="Vacio: captura desactivada. Los borradores pueden permanecer sin respuesta.",
    )
    bekvam_default_partner_id = fields.Many2one(
        related="company_id.l10n_cr_edi_pos_default_partner_id", readonly=True,
    )
