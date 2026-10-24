"""Hardware naming engine for Signal Sudoku.

Generates unique, configurable hardware identifiers following
configurable naming patterns.
"""
from dataclasses import dataclass, field
from typing import Dict, Set, List
import re


@dataclass
class NamingConfig:
    """Configuration for naming patterns.

    Each pattern string is a Python :meth:`str.format` template.  The
    available substitution keys differ per pattern – see the individual
    ``generate_*`` methods on :class:`NamingEngine` for details.
    """
    area: str = 'AR1'
    unit: str = '100'
    cabinet_pattern: str = '{area}-DCS-{unit}-{seq:02d}'
    controller_pattern: str = '{area}CTL{unit}{seq:02d}'
    marshalling_pattern: str = '{area}-DCM-{unit}-{seq:02d}'
    cioc_pattern: str = '{area}CIOC{unit}{seq:03d}'
    baseplate_pattern: str = '{cioc_seq:03d}-CBP-{seq}'
    cabinet_start_seq: int = 1
    cioc_start_seq: int = 1
    baseplate_start_seq: int = 1


class NamingEngine:
    """Generates unique, collision-free hardware identifiers.

    All generated names are tracked internally so that collisions can be
    detected both eagerly (at generation time) and via the
    :meth:`validate_names` batch check.
    """

    # Characters considered valid in a hardware identifier.
    _VALID_NAME_RE = re.compile(r'^[A-Za-z0-9\-_]+$')

    def __init__(self, config: NamingConfig = None) -> None:
        """Initialise the naming engine.

        Args:
            config: Optional :class:`NamingConfig`.  Defaults are used when
                *None*.
        """
        self.config: NamingConfig = config if config is not None else NamingConfig()
        self._generated_names: Set[str] = set()

        # Internal sequence counters
        self._cabinet_seq: int = self.config.cabinet_start_seq
        self._cioc_seq: int = self.config.cioc_start_seq
        self._baseplate_seq: int = self.config.baseplate_start_seq

    # ------------------------------------------------------------------
    # Public generation methods
    # ------------------------------------------------------------------

    def generate_cabinet_name(self, seq: int) -> str:
        """Generate a cabinet name for the given sequence number.

        Template keys: ``area``, ``unit``, ``seq``.

        Args:
            seq: Sequence number to substitute into the pattern.

        Returns:
            The formatted cabinet name string.
        """
        name = self.config.cabinet_pattern.format(
            area=self.config.area,
            unit=self.config.unit,
            seq=seq,
        )
        self._generated_names.add(name)
        return name

    def generate_controller_name(self, seq: int) -> str:
        """Generate a controller name for the given sequence number.

        Template keys: ``area``, ``unit``, ``seq``.
        """
        name = self.config.controller_pattern.format(
            area=self.config.area,
            unit=self.config.unit,
            seq=seq,
        )
        self._generated_names.add(name)
        return name

    def generate_marshalling_name(self, seq: int) -> str:
        """Generate a marshalling cabinet name for the given sequence number.

        Template keys: ``area``, ``unit``, ``seq``.
        """
        name = self.config.marshalling_pattern.format(
            area=self.config.area,
            unit=self.config.unit,
            seq=seq,
        )
        self._generated_names.add(name)
        return name

    def generate_cioc_name(self, seq: int) -> str:
        """Generate a CIOC name for the given sequence number.

        Template keys: ``area``, ``unit``, ``seq``.
        """
        name = self.config.cioc_pattern.format(
            area=self.config.area,
            unit=self.config.unit,
            seq=seq,
        )
        self._generated_names.add(name)
        return name

    def generate_baseplate_name(self, cioc_seq: int, bp_seq: int) -> str:
        """Generate a baseplate name.

        Template keys: ``cioc_seq``, ``seq``.

        Args:
            cioc_seq: The parent CIOC sequence number.
            bp_seq: The baseplate sequence number within the CIOC.
        """
        name = self.config.baseplate_pattern.format(
            cioc_seq=cioc_seq,
            seq=bp_seq,
        )
        self._generated_names.add(name)
        return name

    def generate_charm_id(self, cioc_seq: int, bp_seq: int, charm_seq: int) -> str:
        """Generate a CHARM identifier.

        Format: ``{baseplate_name}-CHM-{charm_seq}``.

        Args:
            cioc_seq: The parent CIOC sequence number.
            bp_seq: The baseplate sequence number.
            charm_seq: The CHARM position (1-based) within the baseplate.
        """
        bp_name = self.config.baseplate_pattern.format(
            cioc_seq=cioc_seq,
            seq=bp_seq,
        )
        name = f'{bp_name}-CHM-{charm_seq}'
        self._generated_names.add(name)
        return name

    # ------------------------------------------------------------------
    # Auto-incrementing convenience helpers
    # ------------------------------------------------------------------

    def next_cabinet_seq(self) -> int:
        """Return the next cabinet sequence number and advance the counter."""
        seq = self._cabinet_seq
        self._cabinet_seq += 1
        return seq

    def next_cioc_seq(self) -> int:
        """Return the next CIOC sequence number and advance the counter."""
        seq = self._cioc_seq
        self._cioc_seq += 1
        return seq

    def next_baseplate_seq(self) -> int:
        """Return the next baseplate sequence number and advance the counter."""
        seq = self._baseplate_seq
        self._baseplate_seq += 1
        return seq

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_names(self, names: list[str]) -> list[dict]:
        """Validate a list of hardware names for duplicates and invalid characters.

        Args:
            names: List of name strings to validate.

        Returns:
            A list of finding dicts.  Each dict has keys:
            ``name``, ``issue`` (str description), ``severity`` ('error' or
            'warning').
        """
        findings: list[dict] = []
        seen: dict[str, int] = {}

        for idx, name in enumerate(names):
            # Check for invalid characters
            if not self._VALID_NAME_RE.match(name):
                findings.append({
                    'name': name,
                    'issue': f"Name contains invalid characters (only alphanumeric, hyphen, underscore allowed): '{name}'",
                    'severity': 'error',
                })

            # Check for empty name
            if not name.strip():
                findings.append({
                    'name': name,
                    'issue': 'Name is empty or whitespace-only',
                    'severity': 'error',
                })
                continue

            # Duplicate detection
            if name in seen:
                findings.append({
                    'name': name,
                    'issue': f"Duplicate name '{name}' (first seen at index {seen[name]}, duplicate at index {idx})",
                    'severity': 'error',
                })
            else:
                seen[name] = idx

        return findings

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset_sequences(self) -> None:
        """Reset all internal sequence counters and clear the name registry."""
        self._cabinet_seq = self.config.cabinet_start_seq
        self._cioc_seq = self.config.cioc_start_seq
        self._baseplate_seq = self.config.baseplate_start_seq
        self._generated_names.clear()

    @property
    def generated_names(self) -> Set[str]:
        """Return a copy of all names generated so far."""
        return set(self._generated_names)
