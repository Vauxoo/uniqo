"""Business rules shared by the ORM adapter and standalone tests. No Odoo imports."""

VISITS = [("first_visit", "Primera visita"), ("previous_visit", "Visita previa")]
CHANNELS = [
    ("facebook", "Facebook"), ("instagram", "Instagram"), ("tiktok", "TikTok"),
    ("google", "Google"), ("referral", "Referido"), ("mall", "Mall"),
]
FINAL_STATES = frozenset(("paid", "done", "invoiced"))


def pair_error(visit, channel, required=False):
    if not visit and not channel and not required:
        return None
    if visit not in dict(VISITS):
        return "Indique si es la primera visita a una tienda Bekvam."
    if visit == "first_visit" and not channel and not required:
        return None  # Incomplete drafts are allowed; finalization checks completeness.
    if visit == "first_visit" and channel not in dict(CHANNELS):
        return "Seleccione como conocio Bekvam para la primera visita."
    if visit == "previous_visit" and channel:
        return "Una visita previa no debe conservar un canal de primera visita."
    return None


def has_new_purchase(lines):
    """The total may be zero: an exchange still contains a new purchase."""
    return any(float(line.get("qty", 0)) > 0 for line in lines)


def ui_lines(commands):
    """Only the complete line snapshots emitted by Odoo 16 POS are accepted."""
    result = []
    for command in commands or []:
        if (not isinstance(command, (list, tuple)) or len(command) != 3
                or command[0] != 0 or not isinstance(command[2], dict)):
            raise ValueError("Formato de lineas TPV no admitido para validar el origen.")
        result.append(command[2])
    return result
