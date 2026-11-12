#!/usr/bin/env python3
"""Gate fresh per-account quota before flight dispatch.

Uso:
    python scripts/flight/quota_gate.py --target-instance <providerInstanceId> --flight-dir <VUELO>
    Options: --supervision-policy strict|deferred, --strict-map, --supervisor-instance <id>

Before: a flight directory contains a UTF-8 JSON ``flight_roster.json`` with
    quota thresholds and an account provider map.
During: resolve the destination, run quota_tick.py in a fresh subprocess, and
    evaluate destination and supervision accounts fail-closed.
After: print one human-readable gate line and a filtered schema-v2 JSON payload,
    returning 0, 3, 4, 5, or 9 according to the measured result.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


SOFT_DEFAULT = 92
HARD_DEFAULT = 97
HARD_SUPERVISION = 97
TIMEOUT_S = 60
RC = {"NO_MEDIDO": 9, "HARD": 5, "FREEZE": 4, "AVISO": 3, "OK": 0}
SUPERVISION_STRICT = "strict"
SUPERVISION_DEFERRED = "deferred"


class NoMedidoError(Exception):
    """Identify a quota result that cannot be measured or resolved."""


def load_roster(flight_dir):
    """Load the flight roster as a JSON object.

    Before: ``flight_dir`` identifies a directory containing flight_roster.json.
    During: read UTF-8 with optional BOM and parse the complete roster object.
    After: return the roster dictionary or raise ``NoMedidoError`` with its cause.
    """
    try:
        roster = (Path(flight_dir) / "flight_roster.json").read_text(
            encoding="utf-8-sig"
        )
        value = json.loads(roster)
    except (OSError, ValueError, RecursionError) as exc:
        raise NoMedidoError(f"roster: {type(exc).__name__} {exc}") from exc
    if not isinstance(value, dict):
        raise NoMedidoError("roster: no es un objeto JSON")
    return value


def _policy(roster):
    """Return the quota account policy from a roster.

    Before: ``roster`` is the parsed flight roster.
    During: prefer quota.account_policy and tolerate a missing policy as empty.
    After: return the quota dictionary and its account-policy dictionary.
    """
    quota = roster.get("quota", {})
    if not isinstance(quota, dict):
        quota = {}
    policy = quota.get("account_policy", {})
    if not isinstance(policy, dict):
        policy = {}
    return quota, policy


def resolve_target(roster, target_instance):
    """Resolve a target provider instance to its account.

    Before: ``target_instance`` is the provider identity requested for dispatch.
    During: inspect provider-map keys first and then case-insensitive map values.
    After: return ``(account, True)`` or raise a fail-closed ``NoMedidoError``.
    """
    _quota, policy = _policy(roster)
    provider_map = policy.get("provider_map", {})
    if isinstance(provider_map, dict):
        if target_instance in provider_map and isinstance(
            provider_map[target_instance], str
        ):
            return provider_map[target_instance], True
        target_folded = str(target_instance).casefold()
        for value in provider_map.values():
            if isinstance(value, str) and value.casefold() == target_folded:
                return value, True
    raise NoMedidoError(f"destino no resoluble en provider_map: {target_instance}")


def measure(flight_dir):
    """Run quota_tick.py freshly and parse its schema-v2 JSON.

    Before: ``flight_dir`` is the flight directory to measure.
    During: invoke the sibling quota_tick.py with JSON output and a hard timeout.
    After: return its object payload, or raise ``NoMedidoError`` naming the cause.
    """
    command = [
        sys.executable,
        str(Path(__file__).with_name("quota_tick.py")),
        "--json",
        "--flight-dir",
        str(flight_dir),
    ]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise NoMedidoError(f"quota_tick: TimeoutExpired {exc}") from exc
    except OSError as exc:
        raise NoMedidoError(f"quota_tick: {type(exc).__name__} {exc}") from exc
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise NoMedidoError(
            f"quota_tick subprocess rc={completed.returncode}: salida no JSON parseable"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("QUOTA_JSON_SCHEMA") != 2
        or not isinstance(payload.get("accounts"), list)
        or not payload["accounts"]
    ):
        raise NoMedidoError(
            f"quota_tick subprocess rc={completed.returncode}: "
            "salida sin JSON v2 con accounts"
        )
    if completed.returncode in (0, 3, 4, 5):
        return payload
    failed_accounts = [
        entry.get("cuenta")
        for entry in payload["accounts"]
        if isinstance(entry, dict)
        and entry.get("calidad_medida") in ("STALE", "NO_MEDIDO")
        and isinstance(entry.get("cuenta"), str)
    ]
    if failed_accounts:
        names = ", ".join(failed_accounts)
        raise NoMedidoError(
            f"quota_tick subprocess rc={completed.returncode}: "
            f"cuentas stale/no medidas: {names}"
        )
    raise NoMedidoError(
        f"quota_tick subprocess rc={completed.returncode}: sin cuentas stale/no medidas"
    )


def pick_account(payload, account):
    """Select one measured account from a quota payload.

    Before: ``payload`` is a schema-v2 object and ``account`` is the resolved name.
    During: scan only the payload account entries for an exact account name.
    After: return the matching entry or raise ``NoMedidoError``.
    """
    for entry in payload.get("accounts", []):
        if isinstance(entry, dict) and entry.get("cuenta") == account:
            return entry
    raise NoMedidoError(f"cuenta destino no medida: {account}")


def _census(policy):
    """Build the effective account census used for supervision resolution.

    Before: ``policy`` is a roster account policy.
    During: collect map values and preferred/harbor accounts in stable order.
    After: return unique string account names.
    """
    values = []
    provider_map = policy.get("provider_map", {})
    if isinstance(provider_map, dict):
        values.extend(
            value for value in provider_map.values() if isinstance(value, str)
        )
    values.extend(
        value
        for key in ("preferred_account", "harbor_account")
        if isinstance((value := policy.get(key)), str)
    )
    return list(dict.fromkeys(values))


def _resolve_supervisor(quota, policy, explicit):  # noqa: C901
    """Resolve the declared supervision account in contract order.

    Before: ``quota`` and ``policy`` contain supervision declarations.
    During: apply explicit instance, exact reserve census match, and supervisor_account order.
    After: return an account name or raise a fail-closed supervision error. The
        real vuelo-20261026b roster declares reserve_for_orquestadora as prose,
        so operators must pass --supervisor-instance until that roster changes.
    """
    provider_map = policy.get("provider_map", {})
    census = _census(policy)
    if explicit:
        if isinstance(provider_map, dict) and explicit in provider_map:
            value = provider_map[explicit]
            if isinstance(value, str):
                return value
        for value in census:
            if value.casefold() == str(explicit).casefold():
                return value
        raise NoMedidoError("supervision: cuenta no resoluble")
    reserve = quota.get("reserve_for_orquestadora")
    if not isinstance(reserve, str):
        reserve = policy.get("reserve_for_orquestadora")
    if isinstance(reserve, str):
        for value in census:
            if value.casefold() == reserve.strip().casefold():
                return value
    supervisor = policy.get("supervisor_account")
    if isinstance(supervisor, str) and supervisor.strip():
        return supervisor.strip()
    raise NoMedidoError("supervision: sin cuenta de supervision declarada")


def _threshold(quota, key, default):
    """Read one finite positive roster threshold with a safe fallback.

    Before: ``quota`` may contain malformed or absent threshold values.
    During: accept numeric non-boolean values and otherwise use ``default``.
    After: return the effective threshold.
    """
    value = quota.get(key, default)
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else default
    )


def _account_rc(entry, soft, hard):
    """Classify one measured account by quality and block percentage.

    Before: ``entry`` is a quota account record and cuts are effective numbers.
    During: fail closed on stale, unmeasured, or absent percentages, then apply cuts.
    After: return ``(rc, reason)`` for the account.
    """
    quality = entry.get("calidad_medida")
    pct = entry.get("block_pct")
    if quality in ("STALE", "NO_MEDIDO"):
        return 9, "stale" if quality == "STALE" else "no medido"
    if not _is_numeric_pct(pct):
        return 9, "block_pct no numerico"
    if pct >= hard:
        return 5, "hard"
    if pct >= soft:
        return 4, "freeze"
    return 0, "ok"


def _is_numeric_pct(value):
    """Check whether a measured block percentage is a numeric scalar.

    Before: ``value`` may be monitor data of any JSON type.
    During: reject booleans and numeric strings while accepting int and float values.
    After: return a boolean suitable for fail-closed quota classification.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(  # noqa: C901
    roster,
    payload,
    target_instance,
    supervision_policy=SUPERVISION_STRICT,
    strict_map=False,
    supervisor_instance=None,
):
    """Evaluate destination quota, map quality, and optional supervision.

    Before: ``roster`` and ``payload`` are parsed JSON objects for one flight.
    During: resolve destination, apply thresholds and map reserve semantics, then
        combine strict supervision using severity order 0 < 3 < 4 < 5 < 9.
    After: return a result dictionary containing rc, reason, account, and gate metadata.
    """
    try:
        account, via_map = resolve_target(roster, target_instance)
    except NoMedidoError as exc:
        return {
            "rc": 9,
            "motivo": str(exc),
            "cuenta": None,
            "mapa_no_verificado": False,
            "strict_map": strict_map,
            "supervision_policy": supervision_policy,
            "supervision": {
                "cuenta": None,
                "block_pct": None,
                "calidad_medida": None,
                "rc": 9,
            },
        }
    quota, policy = _policy(roster)
    try:
        target = pick_account(payload, account)
    except NoMedidoError as exc:
        return {
            "rc": 9,
            "motivo": str(exc),
            "cuenta": {
                "cuenta": account,
                "calidad_medida": "NO_MEDIDO",
                "block_pct": None,
            },
            "mapa_no_verificado": False,
            "strict_map": strict_map,
            "supervision_policy": supervision_policy,
            "supervision": {
                "cuenta": None,
                "block_pct": None,
                "calidad_medida": None,
                "rc": 9,
            },
        }
    effective_quality = target.get("calidad_medida")
    status = str(policy.get("provider_map_status", ""))
    map_unverified = status.strip().upper().startswith("NO VERIFICADA")
    warning = None
    if map_unverified and via_map and effective_quality == "OK":
        effective_quality = "RESERVA"
        warning = "mapa no verificado: RESERVA"
    target_view = dict(target)
    target_view["calidad_medida"] = effective_quality
    if warning:
        target_view["aviso"] = warning
    soft = _threshold(quota, "soft_freeze_block_pct", SOFT_DEFAULT)
    hard = _threshold(quota, "hard_stop_block_pct", HARD_DEFAULT)
    target_rc, target_reason = _account_rc(target_view, soft, hard)
    if strict_map and effective_quality == "RESERVA":
        target_rc, target_reason = 9, "mapa no verificado (strict-map)"
    supervision = {"cuenta": None, "block_pct": None, "calidad_medida": None, "rc": 0}
    supervision_reason = None
    if supervision_policy != SUPERVISION_DEFERRED:
        try:
            supervisor = _resolve_supervisor(quota, policy, supervisor_instance)
        except NoMedidoError as exc:
            return {
                "rc": 9,
                "motivo": str(exc),
                "cuenta": target_view,
                "mapa_no_verificado": map_unverified,
                "strict_map": strict_map,
                "supervision_policy": supervision_policy,
                "supervision": {
                    "cuenta": None,
                    "block_pct": None,
                    "calidad_medida": None,
                    "rc": 9,
                },
            }
        supervision["cuenta"] = supervisor
        try:
            supervisor_entry = pick_account(payload, supervisor)
        except NoMedidoError:
            supervisor_entry = None
        if supervisor_entry is None or supervisor_entry.get("calidad_medida") in (
            "STALE",
            "NO_MEDIDO",
        ):
            supervision["rc"] = 9
            supervision_reason = "supervision: sin medicion"
        else:
            supervision["block_pct"] = supervisor_entry.get("block_pct")
            supervision["calidad_medida"] = supervisor_entry.get("calidad_medida")
            if not _is_numeric_pct(supervision["block_pct"]):
                supervision["rc"] = 9
                supervision_reason = "supervision: block_pct no numerico"
            elif supervision["block_pct"] >= HARD_SUPERVISION:
                supervision["rc"] = 5
                supervision_reason = "supervision"
    if supervision_policy == SUPERVISION_DEFERRED:
        supervision_reason = None
    final_rc = max(
        target_rc, supervision["rc"], key=lambda value: 9 if value == 9 else value
    )
    if target_rc == final_rc:
        reason = target_reason
    elif supervision["rc"] == final_rc:
        reason = supervision_reason
    else:
        reason = target_reason
    if warning and reason == "ok":
        reason = warning
    return {
        "rc": final_rc,
        "motivo": reason,
        "cuenta": target_view,
        "mapa_no_verificado": map_unverified,
        "strict_map": strict_map,
        "supervision_policy": supervision_policy,
        "supervision": supervision,
    }


def _parser():
    """Build the quota gate argument parser.

    Before: no external state is required.
    During: register required target/flight arguments and supervision controls.
    After: return an argparse parser whose usage failures use rc 2.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-instance", required=True)
    parser.add_argument("--flight-dir", required=True)
    parser.add_argument(
        "--supervision-policy",
        choices=(SUPERVISION_STRICT, SUPERVISION_DEFERRED),
        default=SUPERVISION_STRICT,
    )
    parser.add_argument("--strict-map", action="store_true")
    parser.add_argument("--supervisor-instance", default=None)
    return parser


def _filtered_payload(payload, result, target_instance):
    """Create the schema-v2 output narrowed to the destination account.

    Before: ``payload`` is the full tick result and ``result`` is evaluated gate data.
    During: preserve schema and metadata while replacing accounts and adding gate.
    After: return a compact JSON-serializable output object.
    """
    output = dict(payload)
    output["accounts"] = [result["cuenta"]]
    output["gate"] = {
        "target_instance": target_instance,
        "cuenta_destino": result["cuenta"]["cuenta"],
        "rc": result["rc"],
        "motivo": result["motivo"],
        "mapa_no_verificado": result["mapa_no_verificado"],
        "strict_map": result["strict_map"],
        "supervision_policy": result["supervision_policy"],
        "supervision": result["supervision"],
    }
    return output


def main(argv=None):
    """Run the quota gate command.

    Before: ``argv`` contains the gate command arguments or is None for sys.argv.
    During: load, measure, evaluate, and print the human and JSON results.
    After: return the contractual gate rc, or 9 with a NO_MEDIDO diagnostic.
    """
    args = _parser().parse_args(argv)
    try:
        roster = load_roster(args.flight_dir)
        payload = measure(args.flight_dir)
        result = evaluate(
            roster,
            payload,
            args.target_instance,
            args.supervision_policy,
            args.strict_map,
            args.supervisor_instance,
        )
        if result["cuenta"] is None:
            print(f"QUOTA_GATE NO_MEDIDO {result['motivo']}")
            return RC["NO_MEDIDO"]
        entry = result["cuenta"]
        warning = (
            " ADVERTENCIA mapa no verificado: RESERVA" if entry.get("aviso") else ""
        )
        print(
            f"QUOTA_GATE target={args.target_instance} cuenta={entry['cuenta']} "
            f"calidad={entry.get('calidad_medida')} block_pct={entry.get('block_pct')} "
            f"rc={result['rc']} motivo={result['motivo']}{warning}"
        )
        print(
            json.dumps(
                _filtered_payload(payload, result, args.target_instance),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return result["rc"]
    except NoMedidoError as exc:
        print(f"QUOTA_GATE NO_MEDIDO {exc}")
        return RC["NO_MEDIDO"]


if __name__ == "__main__":
    sys.exit(main())
