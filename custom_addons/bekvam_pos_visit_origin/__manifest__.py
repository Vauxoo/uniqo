{
    "name": "Bekvam POS primera visita",
    "version": "16.0.1.0.0",
    "license": "LGPL-3",
    "author": "Bekvam",
    "category": "Sales/Point of Sale",
    "depends": ["uniqo", "pos_uniqo", "pos_signature", "l10n_cr_edi_pos", "pos_settle_due"],
    "data": ["views/pos_config.xml", "views/pos_order.xml", "views/origin_report.xml"],
    "assets": {
        "point_of_sale.assets": [
            "bekvam_pos_visit_origin/static/src/js/policy.js",
            "bekvam_pos_visit_origin/static/src/js/origin_popup.js",
            "bekvam_pos_visit_origin/static/src/js/models.js",
            "bekvam_pos_visit_origin/static/src/js/screens.js",
            "bekvam_pos_visit_origin/static/src/xml/origin.xml",
            "bekvam_pos_visit_origin/static/src/css/origin.css",
        ],
    },
    "installable": True,
    "application": False,
}
