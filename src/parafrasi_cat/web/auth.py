"""Accés a la interfície: només aquest ordinador, o també la xarxa local.

Per defecte el servidor es lliga a l'amfitrió local i no demana res: és el
comportament de sempre i l'experiència d'ús normal no canvia.

El **mode de xarxa local** és opcional i explícit. Serveix per treballar des
d'un altre dispositiu de la mateixa Wi-Fi —un segon Chromebook amb Chrome i
res més— mentre el motor continua executant-se en aquest ordinador. Com que
llavors el servidor és accessible per a qualsevol màquina de la LAN, s'hi
exigeix:

- un **codi d'accés** de sis xifres, generat amb :mod:`secrets` a cada
  arrencada, que no es desa enlloc ni s'envia enlloc;
- una **sessió** amb un testimoni aleatori, en memòria, que caduca sola i
  desapareix en aturar el servidor;
- una comprovació de la capçalera ``Host`` que continua barrant la
  reassignació de noms (*DNS rebinding*): en mode local només l'amfitrió
  local; en mode de xarxa local, també les adreces IP privades, però mai un
  domini d'Internet.

Res d'això no surt de la màquina: no hi ha cap client de xarxa, cap servei
extern, cap túnel i cap telemetria. El servidor només **rep** connexions.
"""

from __future__ import annotations

import ipaddress
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

#: Noms que sempre identifiquen aquesta mateixa màquina. Es comparen amb
#: l'amfitrió ja net (sense port ni claudàtors d'IPv6), de manera que aquí hi
#: van les formes nues: «[::1]:8765» arriba com a «::1».
LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})

#: Nom de la galeta de sessió.
SESSION_COOKIE = "parafrasi_sessio"

#: Xifres del codi d'accés. Sis són fàcils de dictar i donen un milió de
#: combinacions.
PIN_DIGITS = 6

#: Intents erronis seguits abans de plegar el pany. Un milió de combinacions
#: es proven en menys d'una hora si el servidor les contesta totes: amb aquest
#: límit, provar-les totes demana anys. El comptador és de tot el servidor i no
#: per adreça, perquè a la xarxa local qualsevol pot canviar-se l'adreça.
MAX_FAILED_PINS = 10

#: Temps que dura el pany plegat, en segons.
LOCKOUT_SECONDS = 60.0

#: Durada d'una sessió sense fer res, en segons (sis hores).
DEFAULT_SESSION_TTL = 6 * 60 * 60

#: Rutes que no exigeixen sessió ni en mode de xarxa local: la pantalla
#: d'entrada, els seus fitxers i la comprovació de l'estat d'accés.
PUBLIC_PATHS: frozenset[str] = frozenset({"/api/access"})


class AccessMode(StrEnum):
    """Des d'on es pot obrir la interfície."""

    LOCAL = "local"
    """Només aquest ordinador (per defecte)."""

    LAN = "lan"
    """També altres dispositius de la mateixa xarxa local, amb codi d'accés."""

    @property
    def label(self) -> str:
        return "Només aquest ordinador" if self is AccessMode.LOCAL else "Xarxa local"

    @property
    def description(self) -> str:
        if self is AccessMode.LOCAL:
            return "La interfície només s'obre en aquest ordinador."
        return (
            "Permet accedir a Parafrasi-cat des d'un altre dispositiu connectat a la "
            "mateixa xarxa local. El motor continua executant-se en aquest ordinador."
        )

    @property
    def requires_authentication(self) -> bool:
        return self is AccessMode.LAN


#: Avís que acompanya sempre el mode de xarxa local.
NETWORK_WARNING = (
    "Utilitza aquesta funció només en una xarxa Wi-Fi privada i de confiança. "
    "La connexió dins de la xarxa local és HTTP i no va xifrada: qui tingui accés a "
    "la mateixa xarxa podria veure el text que hi circula."
)

#: Com és la privacitat en cada mode, en termes exactes.
PRIVACY_NOTES: dict[AccessMode, str] = {
    AccessMode.LOCAL: "El text no surt d'aquest ordinador.",
    AccessMode.LAN: (
        "El text només circula dins de la xarxa local entre el navegador client i "
        "l'ordinador que executa Parafrasi-cat. No s'envia a cap servei d'Internet."
    ),
}


def generate_pin(digits: int = PIN_DIGITS) -> str:
    """Codi d'accés aleatori, amb un generador criptogràfic i sense biaix."""
    if digits < 4:
        raise ValueError("El codi d'accés ha de tenir almenys quatre xifres")
    return str(secrets.randbelow(10**digits)).zfill(digits)


def _bare_host(header: str) -> str:
    """Amfitrió de la capçalera ``Host``, sense port i sense claudàtors d'IPv6."""
    host = header.strip()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end > 0 else host[1:]
    if host.count(":") == 1:  # nom:port o IPv4:port
        host = host.rsplit(":", 1)[0]
    return host


#: Espai d'adreces compartit (RFC 6598). Python no el considera privat, però
#: ChromeOS hi posa el contenidor de Linux: 100.115.92.x.
SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")

#: Dominis de primer nivell reservats (RFC 6761 i RFC 8375): no es poden
#: registrar a Internet, de manera que ningú no en pot fer apuntar un cap aquí.
#: Crostini fa servir «penguin.linux.test».
RESERVED_SUFFIXES = (".localhost", ".test", ".home.arpa")


def _is_local_network_address(host: str) -> bool:
    """Cert si és una adreça d'aquesta màquina o de la xarxa local.

    Un domini d'Internet no ho és mai: així una pàgina externa no pot arribar
    al servidor fent que el seu domini apunti a una adreça privada. Els noms
    sota un TLD reservat sí que s'accepten, perquè no són registrables.
    """
    name = host.rstrip(".").lower()
    if name.endswith(RESERVED_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    if address.version == 4 and address in SHARED_ADDRESS_SPACE:
        return True
    return (
        address.is_loopback or address.is_private or address.is_link_local or address.is_unspecified
    )


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Qui pot arribar al servidor i què ha de demostrar per entrar."""

    mode: AccessMode = AccessMode.LOCAL
    pin: str = ""
    """Codi d'accés (buit en mode local, on no se'n demana cap)."""
    extra_hosts: frozenset[str] = frozenset()
    """Amfitrions acceptats a més dels habituals (p. ex. el nom configurat)."""

    @classmethod
    def local(cls) -> AccessPolicy:
        return cls(AccessMode.LOCAL)

    @classmethod
    def lan(cls, pin: str | None = None, *, extra_hosts: Iterable[str] = ()) -> AccessPolicy:
        """Política de xarxa local amb un codi d'accés nou si no se'n dona cap."""
        return cls(
            AccessMode.LAN,
            pin or generate_pin(),
            frozenset(h.strip().lower() for h in extra_hosts if h.strip()),
        )

    @property
    def requires_authentication(self) -> bool:
        return self.mode.requires_authentication

    def host_allowed(self, header: str | None) -> bool:
        """Cert si la capçalera ``Host`` correspon a aquesta màquina o a la LAN.

        Sense capçalera (HTTP/1.0) es deixa passar, com fins ara. Un domini
        d'Internet es rebutja sempre, en tots dos modes.
        """
        # El punt final de la forma absoluta («localhost.») no canvia l'amfitrió.
        host = _bare_host(header or "").lower().rstrip(".")
        if not host or host in LOCAL_HOSTS:
            return True
        if self.mode is AccessMode.LOCAL:
            return False
        if host in self.extra_hosts:
            return True
        return _is_local_network_address(host)

    def pin_matches(self, candidate: str) -> bool:
        """Comparació en temps constant del codi d'accés.

        Es comparen els bytes i no les cadenes: :func:`secrets.compare_digest`
        només accepta text ASCII, i qui envia el codi tria què hi posa. Amb
        bytes, un codi amb accents dona un «no» net en comptes d'una excepció.
        """
        if not self.pin:
            return False
        return secrets.compare_digest(self.pin.encode("utf-8"), candidate.strip().encode("utf-8"))

    def to_dict(self) -> dict[str, object]:
        """Estat públic: mai no hi surt el codi d'accés."""
        return {
            "mode": self.mode.value,
            "label": self.mode.label,
            "description": self.mode.description,
            "requires_authentication": self.requires_authentication,
            "privacy": PRIVACY_NOTES[self.mode],
            "warning": NETWORK_WARNING if self.mode is AccessMode.LAN else "",
        }


class SessionStore:
    """Sessions obertes, només en memòria: testimoni aleatori i caducitat.

    No es desa res a disc, no hi ha cap testimoni al repositori i tot
    desapareix quan s'atura el servidor. El rellotge és injectable per poder
    provar la caducitat sense esperar.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_SESSION_TTL,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("La durada de la sessió ha de ser positiva")
        self._ttl = ttl_seconds
        self._clock = clock
        self._tokens: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def create(self) -> str:
        """Obre una sessió i retorna el seu testimoni."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge()
            self._tokens[token] = self._clock() + self._ttl
        return token

    def valid(self, token: str | None) -> bool:
        """Cert si el testimoni existeix i no ha caducat (i n'allarga la vida)."""
        if not token:
            return False
        with self._lock:
            self._purge()
            if token not in self._tokens:
                return False
            self._tokens[token] = self._clock() + self._ttl
            return True

    def revoke(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._tokens.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._tokens.clear()

    def __len__(self) -> int:
        with self._lock:
            self._purge()
            return len(self._tokens)

    def _purge(self) -> None:
        now = self._clock()
        expired = [token for token, deadline in self._tokens.items() if deadline <= now]
        for token in expired:
            del self._tokens[token]


class AttemptLimiter:
    """Frena la prova sistemàtica del codi d'accés a la xarxa local.

    Compta els intents erronis de tot el servidor: passats
    :data:`MAX_FAILED_PINS` seguits, no s'accepta cap codi durant
    :data:`LOCKOUT_SECONDS`, encara que sigui el bo. Un encert esborra el
    comptador. El rellotge és injectable per poder-ho provar sense esperar.
    """

    def __init__(
        self,
        limit: int = MAX_FAILED_PINS,
        lockout_seconds: float = LOCKOUT_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("El límit d'intents ha de ser positiu")
        if lockout_seconds <= 0:
            raise ValueError("La durada del pany plegat ha de ser positiva")
        self._limit = limit
        self._lockout = lockout_seconds
        self._clock = clock
        self._failures = 0
        self._until = 0.0
        self._lock = threading.Lock()

    @property
    def lockout_seconds(self) -> float:
        return self._lockout

    def blocked_for(self) -> float:
        """Segons que falten per poder tornar a provar (zero si es pot ara)."""
        with self._lock:
            return max(0.0, self._until - self._clock())

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._limit:
                self._failures = 0
                self._until = self._clock() + self._lockout

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._until = 0.0

    def reset(self) -> None:
        self.record_success()


def cookie_value(header: str | None, name: str = SESSION_COOKIE) -> str | None:
    """Valor d'una galeta a la capçalera ``Cookie`` (sense dependre de http.cookies)."""
    for part in (header or "").split(";"):
        key, _, value = part.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def cookie_header(token: str, ttl_seconds: float, name: str = SESSION_COOKIE) -> str:
    """Galeta de sessió: només per al servidor, del mateix lloc i amb caducitat.

    No porta ``Secure`` perquè la xarxa local és HTTP; això queda documentat
    com una limitació del mode, no com un descuit.
    """
    return f"{name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={int(ttl_seconds)}"


def expired_cookie(name: str = SESSION_COOKIE) -> str:
    return f"{name}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


@dataclass(frozen=True, slots=True)
class ServerStatus:
    """El que s'escriu a la consola en arrencar, perquè es vegi d'un cop d'ull."""

    mode: AccessMode
    port: int
    components: tuple[tuple[str, str], ...] = ()
    pin: str = ""
    url: str = ""
    extra: tuple[str, ...] = field(default_factory=tuple)

    def lines(self) -> list[str]:
        lines = [
            "Parafrasi-cat",
            f"Mode: {self.mode.label}",
            f"Port: {self.port}",
            f"Autenticació: {'activa' if self.mode.requires_authentication else 'no cal'}",
            "Motor: actiu",
        ]
        lines.extend(f"{name}: {state}" for name, state in self.components)
        if self.pin:
            lines.extend(["", f"Codi d'accés: {self.pin}"])
        if self.url:
            lines.extend(["", f"En aquest ordinador: {self.url}"])
        lines.extend(self.extra)
        return lines

    def render(self) -> str:
        return "\n".join(self.lines())


__all__ = [
    "DEFAULT_SESSION_TTL",
    "LOCAL_HOSTS",
    "RESERVED_SUFFIXES",
    "SHARED_ADDRESS_SPACE",
    "NETWORK_WARNING",
    "LOCKOUT_SECONDS",
    "MAX_FAILED_PINS",
    "PIN_DIGITS",
    "PRIVACY_NOTES",
    "PUBLIC_PATHS",
    "SESSION_COOKIE",
    "AccessMode",
    "AttemptLimiter",
    "AccessPolicy",
    "ServerStatus",
    "SessionStore",
    "cookie_header",
    "cookie_value",
    "expired_cookie",
    "generate_pin",
]
