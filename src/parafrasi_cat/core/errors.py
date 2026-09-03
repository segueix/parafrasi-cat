"""Jerarquia d'excepcions del motor."""


class ParafrasiError(Exception):
    """Error base de ``parafrasi_cat``."""


class TransformationError(ParafrasiError):
    """Una transformació no es pot aplicar al text indicat."""


class ResourceError(ParafrasiError):
    """No s'ha trobat o no es pot llegir un recurs lingüístic."""


class ConfigError(ParafrasiError):
    """La configuració és invàlida o incoherent."""
