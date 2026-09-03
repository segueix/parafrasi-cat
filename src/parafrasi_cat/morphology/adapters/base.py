"""Base dels adaptadors que invoquen una eina local per subprocés."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence

from parafrasi_cat.core.errors import ResourceError


class MorphologyUnavailableError(ResourceError):
    """L'eina externa que necessita l'adaptador no està instal·lada."""


class ExternalToolAdapter:
    """Executa una eina de línia d'ordres instal·lada localment.

    Mai no obre connexions de xarxa: només invoca un executable del sistema
    amb el text per l'entrada estàndard.
    """

    def __init__(self, command: str, *, timeout: float = 30.0) -> None:
        if not command:
            raise ResourceError("Cal indicar l'ordre de l'eina externa")
        self._command = command
        self._timeout = timeout

    @property
    def command(self) -> str:
        return self._command

    def is_available(self) -> bool:
        return shutil.which(self._command) is not None

    def require(self) -> None:
        if not self.is_available():
            raise MorphologyUnavailableError(
                f"L'eina «{self._command}» no està instal·lada o no és al PATH"
            )

    def run(self, args: Sequence[str], input_text: str) -> str:
        self.require()
        try:
            completed = subprocess.run(  # noqa: S603 - ordre local configurada per l'usuari
                [self._command, *args],
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ResourceError(f"No s'ha pogut executar «{self._command}»: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()
            raise ResourceError(
                f"«{self._command}» ha fallat (codi {completed.returncode}): {detail}"
            )
        return completed.stdout
