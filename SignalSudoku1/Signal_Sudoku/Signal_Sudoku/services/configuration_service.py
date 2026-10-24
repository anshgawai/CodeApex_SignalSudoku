"""Configuration management service for Signal Sudoku.

Manages rule configuration with JSON persistence,
defaults, validation, and reset capabilities.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from copy import deepcopy

DEFAULT_RULES: Dict[str, Any] = {
    'charms_per_baseplate': 12,
    'baseplates_per_cioc': 8,
    'ciocs_per_cabinet': 4,
    'keep_groups_together': True,
    'enforce_segregation': True,
    'keep_cables_together': True,
    'maintain_pair_order': True,
    'reserve_spare_capacity': False,
    'spare_baseplates_per_cioc': 0,
    'spare_percentage': 10.0,
    'default_do_subtype': 'normal',
    'naming': {
        'area': 'AR1',
        'unit': '100',
        'cabinet_pattern': '{area}-DCS-{unit}-{seq:02d}',
        'controller_pattern': '{area}CTL{unit}{seq:02d}',
        'marshalling_pattern': '{area}-DCM-{unit}-{seq:02d}',
        'cioc_pattern': '{area}CIOC{unit}{seq:03d}',
        'baseplate_pattern': '{cioc_seq:03d}-CBP-{seq}',
        'cabinet_start_seq': 1,
        'cioc_start_seq': 1,
        'baseplate_start_seq': 1,
    },
    'enabled_rules': {
        'capacity_limits': True,
        'one_signal_per_charm': True,
        'segregation': True,
        'signal_charm_mapping': True,
        'terminal_block_mapping': True,
        'unique_naming': True,
        'cable_grouping': True,
        'pair_ordering': True,
        'spare_capacity': False,
        'group_together': True,
    },
}

# Keys that must be positive integers
_POSITIVE_INT_KEYS = {
    'charms_per_baseplate',
    'baseplates_per_cioc',
    'ciocs_per_cabinet',
}

# Keys that must be non-negative integers
_NON_NEGATIVE_INT_KEYS = {
    'spare_baseplates_per_cioc',
}

# Keys that must be non-negative floats
_NON_NEGATIVE_FLOAT_KEYS = {
    'spare_percentage',
}

# Keys that must be boolean
_BOOLEAN_KEYS = {
    'keep_groups_together',
    'enforce_segregation',
    'keep_cables_together',
    'maintain_pair_order',
    'reserve_spare_capacity',
}

_VALID_DO_SUBTYPES = {'normal', 'solenoid', 'relay'}

CONFIG_FILE_NAME = 'user_rules.json'


class ConfigurationService:
    """Manages I/O allocation rule configuration with JSON persistence.

    Rules are stored as a JSON file inside *config_dir*.  On first access
    the defaults are used; subsequent saves persist to disk so the
    configuration survives application restarts.
    """

    def __init__(self, config_dir: str = 'config') -> None:
        """Initialise the service.

        Args:
            config_dir: Directory (relative or absolute) where the
                        configuration JSON file is stored.  Created
                        automatically if it does not exist.
        """
        self._config_dir = Path(config_dir)
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self._config_dir / CONFIG_FILE_NAME
        self._rules: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> Dict[str, Any]:
        """Load rules from the JSON file, falling back to defaults."""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as fh:
                    loaded = json.load(fh)
                # Merge with defaults so that newly-added keys are present
                merged = deepcopy(DEFAULT_RULES)
                self._deep_merge(merged, loaded)
                return merged
            except (json.JSONDecodeError, OSError):
                return deepcopy(DEFAULT_RULES)
        return deepcopy(DEFAULT_RULES)

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Recursively merge *override* into *base* in-place."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigurationService._deep_merge(base[key], value)
            else:
                base[key] = value

    def _persist(self) -> None:
        """Write the current rules to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, 'w', encoding='utf-8') as fh:
            json.dump(self._rules, fh, indent=4, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_rules(self) -> Dict[str, Any]:
        """Return the current rules, loading from disk if necessary.

        Returns:
            A deep copy of the active rule set.
        """
        if self._rules is None:
            self._rules = self._load_from_disk()
        return deepcopy(self._rules)

    def save_rules(self, rules: Dict[str, Any]) -> None:
        """Save the provided rules dict to disk and cache them.

        Args:
            rules: Complete rules dictionary to persist.
        """
        self._rules = deepcopy(rules)
        self._persist()

    def reset_to_defaults(self) -> Dict[str, Any]:
        """Reset rules to built-in defaults, persist, and return them.

        Returns:
            A deep copy of the default rule set.
        """
        self._rules = deepcopy(DEFAULT_RULES)
        self._persist()
        return deepcopy(self._rules)

    def update_rule(self, key: str, value: Any) -> Dict[str, Any]:
        """Update a single top-level rule key, persist, and return all rules.

        For nested keys (e.g. ``naming.area``), use dot-notation.

        Args:
            key: Rule key, optionally dot-separated for nested values.
            value: New value to set.

        Returns:
            A deep copy of the updated rule set.
        """
        rules = self.get_rules()
        parts = key.split('.')
        target = rules
        for part in parts[:-1]:
            if part in target and isinstance(target[part], dict):
                target = target[part]
            else:
                target[part] = {}
                target = target[part]
        target[parts[-1]] = value
        self.save_rules(rules)
        return deepcopy(self._rules)

    def validate_rules(self, rules: Dict[str, Any]) -> List[str]:
        """Validate rule values and return a list of error messages.

        Checks include:
        - Positive-integer constraints (charms, baseplates, CIOCs per cabinet)
        - Non-negative integer/float constraints
        - Boolean type checks
        - Valid DO subtype

        Args:
            rules: Rules dictionary to validate.

        Returns:
            List of human-readable error strings.  Empty list means valid.
        """
        errors: List[str] = []

        for key in _POSITIVE_INT_KEYS:
            val = rules.get(key)
            if val is None:
                errors.append(f"'{key}' is required.")
            elif not isinstance(val, (int, float)) or int(val) != val or int(val) < 1:
                errors.append(f"'{key}' must be a positive integer (got {val!r}).")

        for key in _NON_NEGATIVE_INT_KEYS:
            val = rules.get(key)
            if val is not None:
                if not isinstance(val, (int, float)) or int(val) != val or int(val) < 0:
                    errors.append(f"'{key}' must be a non-negative integer (got {val!r}).")

        for key in _NON_NEGATIVE_FLOAT_KEYS:
            val = rules.get(key)
            if val is not None:
                if not isinstance(val, (int, float)) or val < 0:
                    errors.append(f"'{key}' must be a non-negative number (got {val!r}).")

        for key in _BOOLEAN_KEYS:
            val = rules.get(key)
            if val is not None and not isinstance(val, bool):
                errors.append(f"'{key}' must be a boolean (got {type(val).__name__}).")

        do_sub = rules.get('default_do_subtype')
        if do_sub is not None and do_sub not in _VALID_DO_SUBTYPES:
            errors.append(
                f"'default_do_subtype' must be one of {sorted(_VALID_DO_SUBTYPES)} "
                f"(got {do_sub!r})."
            )

        # Validate naming sub-dict if present
        naming = rules.get('naming')
        if naming is not None:
            if not isinstance(naming, dict):
                errors.append("'naming' must be a dictionary.")
            else:
                for seq_key in ('cabinet_start_seq', 'cioc_start_seq', 'baseplate_start_seq'):
                    seq_val = naming.get(seq_key)
                    if seq_val is not None:
                        if not isinstance(seq_val, (int, float)) or int(seq_val) != seq_val or int(seq_val) < 1:
                            errors.append(f"'naming.{seq_key}' must be a positive integer (got {seq_val!r}).")

        # Validate enabled_rules sub-dict
        enabled = rules.get('enabled_rules')
        if enabled is not None:
            if not isinstance(enabled, dict):
                errors.append("'enabled_rules' must be a dictionary.")
            else:
                for er_key, er_val in enabled.items():
                    if not isinstance(er_val, bool):
                        errors.append(f"'enabled_rules.{er_key}' must be a boolean (got {type(er_val).__name__}).")

        return errors

    def get_defaults(self) -> Dict[str, Any]:
        """Return a deep copy of the built-in default rules.

        Returns:
            Default rules dictionary.
        """
        return deepcopy(DEFAULT_RULES)

    def export_config(self) -> str:
        """Serialise the current configuration to a JSON string.

        Returns:
            Pretty-printed JSON string.
        """
        return json.dumps(self.get_rules(), indent=4, ensure_ascii=False)

    def import_config(self, json_str: str) -> Dict[str, Any]:
        """Import configuration from a JSON string, persist, and return it.

        Args:
            json_str: JSON-encoded rules dictionary.

        Returns:
            The imported (and now active) rules.

        Raises:
            json.JSONDecodeError: If *json_str* is not valid JSON.
            ValueError: If the parsed JSON is not a dictionary.
        """
        parsed = json.loads(json_str)
        if not isinstance(parsed, dict):
            raise ValueError("Imported configuration must be a JSON object (dict).")
        # Merge with defaults so missing keys are filled in
        merged = deepcopy(DEFAULT_RULES)
        self._deep_merge(merged, parsed)
        self.save_rules(merged)
        return deepcopy(self._rules)
