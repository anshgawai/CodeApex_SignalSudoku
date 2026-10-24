"""Signal classification engine for Signal Sudoku.

Classifies I/O signals into hardware types (CHARM type, terminal block type)
based on configurable mapping rules.
"""
from dataclasses import dataclass, field
from typing import Optional
import re
import copy


@dataclass
class SignalClassification:
    """Result of classifying a signal."""
    charm_type: str  # e.g., 'AI CHARM (HART)', 'AO CHARM', 'DI CHARM', 'Isolated DO CHARM', 'High-side DO CHARM'
    terminal_block: str  # e.g., 'Standard', 'Fused-injected-power', 'Relay output'
    io_category: str  # AI, AO, DI, DO
    do_subtype: Optional[str] = None  # 'high_current', 'normal', 'relay' for DO signals
    confidence: str = 'definite'  # 'definite', 'default', 'uncertain'
    notes: str = ''


# Default signal classification mapping
DEFAULT_CLASSIFICATION_MAP = {
    'AI': SignalClassification(
        charm_type='AI CHARM (HART)',
        terminal_block='Standard',
        io_category='AI'
    ),
    'AO': SignalClassification(
        charm_type='AO CHARM',
        terminal_block='Standard',
        io_category='AO'
    ),
    'DI': SignalClassification(
        charm_type='DI CHARM',
        terminal_block='Standard',
        io_category='DI'
    ),
    'DO': SignalClassification(
        charm_type='High-side DO CHARM',
        terminal_block='Standard',
        io_category='DO',
        do_subtype='normal',
        confidence='default',
        notes='DO subtype not specified; defaulting to normal DO'
    ),
    'DO_HIGH_CURRENT': SignalClassification(
        charm_type='Isolated DO CHARM',
        terminal_block='Fused-injected-power',
        io_category='DO',
        do_subtype='high_current'
    ),
    'DO_RELAY': SignalClassification(
        charm_type='High-side DO CHARM',
        terminal_block='Relay output',
        io_category='DO',
        do_subtype='relay'
    ),
}


class SignalClassifier:
    """Classifies I/O signals into hardware types based on configurable mapping rules.

    The classifier uses a mapping dictionary that maps IO type strings to
    SignalClassification objects. Custom mappings can be provided at
    construction time or updated later via update_mapping().
    """

    def __init__(
        self,
        classification_map: Optional[dict] = None,
        default_do_subtype: str = 'normal',
    ) -> None:
        """Initialise the classifier.

        Args:
            classification_map: Optional custom mapping of IO type strings to
                SignalClassification objects.  If *None*, the module-level
                DEFAULT_CLASSIFICATION_MAP is used.
            default_do_subtype: The DO subtype to assume when a bare 'DO' IO
                type is encountered and no more-specific key is found.
                Must be one of 'normal', 'high_current', or 'relay'.
        """
        if classification_map is not None:
            # Deep-copy so mutations don't leak back to the caller's dict
            self._map: dict[str, SignalClassification] = copy.deepcopy(classification_map)
        else:
            self._map = copy.deepcopy(DEFAULT_CLASSIFICATION_MAP)

        self._default_do_subtype = default_do_subtype

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        io_type: str,
        tag: str = '',
        description: str = '',
    ) -> SignalClassification:
        """Classify a single signal based on its IO type.

        The method performs a case-insensitive lookup in the classification map.
        For DO signals that lack subtype information the configured default DO
        subtype is used and the confidence level is set to ``'default'``.

        Args:
            io_type: The IO type string (e.g. ``'AI'``, ``'DO_HIGH_CURRENT'``).
            tag: Optional signal tag – reserved for future heuristic use.
            description: Optional signal description – reserved for future
                heuristic use.

        Returns:
            A :class:`SignalClassification` instance describing the result.
        """
        if io_type is None:
            io_type = ''

        normalised = io_type.strip().upper()

        if normalised == '':
            return SignalClassification(
                charm_type='Unknown',
                terminal_block='Unknown',
                io_category='Unknown',
                confidence='uncertain',
                notes='IO type is empty',
            )

        # Direct lookup (exact match after normalisation)
        if normalised in self._map:
            return copy.deepcopy(self._map[normalised])

        # For bare 'DO' where only subtype-specific keys exist, resolve via
        # the default DO subtype setting.
        if normalised == 'DO':
            return self._resolve_default_do()

        # Try stripping common prefixes / suffixes (e.g. leading/trailing
        # whitespace was already handled, but handle underscored variants).
        # Check if normalised starts with a known base type.
        for base in ('AI', 'AO', 'DI', 'DO'):
            if normalised.startswith(base) and normalised in self._map:
                return copy.deepcopy(self._map[normalised])

        # Unknown type
        return SignalClassification(
            charm_type='Unknown',
            terminal_block='Unknown',
            io_category=normalised,
            confidence='uncertain',
            notes=f"Unknown IO type '{io_type.strip()}'; manual classification required",
        )

    def get_supported_types(self) -> list[str]:
        """Return a sorted list of IO type keys currently in the classification map."""
        return sorted(self._map.keys())

    def update_mapping(self, io_type: str, classification: SignalClassification) -> None:
        """Add or overwrite a mapping entry.

        Args:
            io_type: The IO type key (will be stored upper-cased).
            classification: The :class:`SignalClassification` to associate.
        """
        self._map[io_type.strip().upper()] = copy.deepcopy(classification)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_default_do(self) -> SignalClassification:
        """Return a DO classification based on the configured default subtype."""
        subtype = self._default_do_subtype

        # Map subtype name to the classification-map key used for it
        subtype_key_map = {
            'normal': 'DO',
            'high_current': 'DO_HIGH_CURRENT',
            'relay': 'DO_RELAY',
        }
        key = subtype_key_map.get(subtype)
        if key and key in self._map:
            result = copy.deepcopy(self._map[key])
            if result.confidence != 'definite':
                result.confidence = 'default'
            if not result.notes:
                result.notes = f'DO subtype not specified; defaulting to {subtype} DO'
            return result

        # Fall back to a generic DO classification
        return SignalClassification(
            charm_type='High-side DO CHARM',
            terminal_block='Standard',
            io_category='DO',
            do_subtype=subtype,
            confidence='default',
            notes=f'DO subtype not specified; defaulting to {subtype} DO',
        )
