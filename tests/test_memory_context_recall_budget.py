"""WOT-2026-057a: `--recall` es la puerta de EXPANSION y necesita presupuesto.

Contexto medido en el bucle L914 (2026-08-17). Dos defectos opuestos convivian
en el mismo comando:

1. TRUNCABA a 150 chars -- MENOS que el bootstrap (200). La puerta que existe
   para recuperar la leccion ENTERA entregaba menos que el indice del que se
   suponia que expandia, asi que el contenido operativo era inalcanzable por
   TODA via. Con mediana de 877 chars, cortar a 150 deja fuera el 83%.

2. Quitar ese truncado SIN TOPE es peor. Medido sobre las 207 entradas reales:
   `--query gate` -> 42 hits ~12.661 tok; `--query de` -> 197 hits ~47.819 tok.
   `--limit` (default 15) es un tope por CARDINALIDAD, no por bytes: un
   `--limit 100 --query gate` se auto-inflige ~12k tokens en un arranque frio.

El patron adoptado es `maxBytes` de deepseek-harness (§2.3 de la propuesta):
presupuesto en BYTES que AVISA de lo que omite. Un corte que no se declara es
el mismo falso verde que este ticket corrige en el bootstrap.
"""

from __future__ import annotations

import json

import scripts.memory_context as memory_context


def _obs(signal: str, topic: str = "t") -> dict:
    return {
        "timestamp": "2026-08-17T10:00:00Z",
        "topic": topic,
        "signal": signal,
        "source": "test",
        "id": f"obs-{topic}",
    }


def test_recall_emits_full_signal_when_within_budget(monkeypatch, capsys):
    """DoD-1: una señal larga pero dentro del presupuesto llega ENTERA.

    MUTACION ALCANZABLE: reintroducir `[:150]` -> la cola desaparece y el
    assert cae.
    """
    larga = "INICIO " + ("x" * 600) + " FINAL-DE-LA-REGLA"
    monkeypatch.setattr(
        memory_context, "recall_observations", lambda **k: [_obs(larga)]
    )
    monkeypatch.setattr("sys.argv", ["memory_context.py", "--recall", "--query", "x"])

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "FINAL-DE-LA-REGLA" in out, (
        "--recall es la puerta de EXPANSION: si trunca, el contenido operativo "
        "es inalcanzable por toda via"
    )


def test_recall_budget_caps_output_and_says_what_it_omitted(monkeypatch, capsys):
    """DoD-2: ante muchas entradas grandes, se acota Y SE DECLARA lo omitido.

    Las dos mitades importan. Acotar sin avisar reintroduce el truncado
    silencioso que este ticket corrige; avisar sin acotar deja el
    desbordamiento auto-infligido.

    MUTACION ALCANZABLE: quitar el presupuesto -> el output crece sin limite y
    el primer assert cae. Quitar el aviso -> cae el segundo.
    """
    entradas = [_obs("Y" * 3000, topic=f"tema{i}") for i in range(40)]
    monkeypatch.setattr(memory_context, "recall_observations", lambda **k: entradas)
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--recall", "--query", "y", "--limit", "40"]
    )

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert len(out) < 40 * 3000, (
        "sin presupuesto en bytes, --recall permite volcar ~47k tokens con una "
        "query comun: el desbordamiento es auto-infligido"
    )
    assert "omitida" in out.lower() or "omitted" in out.lower(), (
        "un corte que no se declara es el mismo falso verde que este ticket "
        "corrige en el bootstrap"
    )


def test_recall_declares_the_cardinality_cut_too(monkeypatch, capsys):
    """WOT-2026-057a / bucle L915: `--limit` recorta EN SILENCIO.

    Hallazgo del lector-FS: el bloque de omision solo cubria el recorte por
    BYTES. El recorte por CARDINALIDAD -- `--limit`, que vale 15 por defecto y
    es el que mas muerde (`test` -> 80 hits, `de` -> 214) -- no decia nada. El
    agente recibia 15 de 80 sin una sola linea que lo declarase.

    Es el mismo defecto "corte no declarado" que este ticket corrige en el
    indice, un nivel mas arriba y en la puerta que el indice designa como via
    de escape.

    MUTACION ALCANZABLE: quitar el aviso de cardinalidad -> el assert cae.
    """
    import scripts.memory_context as memory_context

    # El pool REAL tiene 80; `--limit` entrega 5 y debe declarar los 75 restantes.
    # Se parchea el mismo simbolo que `main()` invoca (importado en el modulo).
    pool = [_obs("regla corta", topic=f"t{i}") for i in range(80)]

    def _fake(query=None, limit=15):
        # Semantica REAL de `recall_observations`: `filtered[:limit]` siempre.
        # `limit=0` devuelve CERO, no "sin tope" -- el mock anterior implementaba
        # la semantica SUPUESTA y tapaba el defecto (mock drift, bucle L915).
        return pool[:limit]

    monkeypatch.setattr(memory_context, "recall_observations", _fake)
    monkeypatch.setattr(
        "sys.argv",
        ["memory_context.py", "--recall", "--query", "regla", "--limit", "5"],
    )
    memory_context.main()
    out = capsys.readouterr().out

    assert "--limit" in out, (
        "el recorte por CARDINALIDAD no se declara: el agente recibe 5 de 80 "
        "sin saber que existen 75 mas"
    )


# ======================================================== WOT-2026-057b
# Deuda declarada en el cierre de 057a, ahora saldada: --id, ranking y hook.


def test_recall_by_id_returns_that_exact_lesson(monkeypatch, capsys):
    """057b-1: el indice imprime `id: obs-xxx` y AHORA existe comando que lo acepta.

    Hallazgo BA23-H2 del bucle L914: `_format_archive_as_text` empezo a emitir
    `(ticket | id: obs-xxx)` para que el agente pudiera expandir la leccion
    truncada... pero `--recall` solo aceptaba `--query` y `--ticket`. Un puntero
    de expansion sin comando que lo consuma es un callejon sin salida: el agente
    lee un identificador que no puede usar.

    MUTACION ALCANZABLE: quitar la rama `--id` -> cae el primer assert.
    """
    import scripts.memory_context as memory_context

    diana = _obs("REGLA-DIANA-COMPLETA", topic="diana")
    diana["id"] = "obs-la-que-busco"
    otra = _obs("ruido", topic="otra")
    otra["id"] = "obs-no-es-esta"
    monkeypatch.setattr(
        memory_context, "recall_observations", lambda **k: [diana, otra]
    )
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--recall", "--id", "obs-la-que-busco"]
    )

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "REGLA-DIANA-COMPLETA" in out, "--id no devolvio la leccion pedida"
    assert "obs-no-es-esta" not in out, (
        "--id devolvio entradas ajenas: debe resolver un identificador EXACTO, "
        "no hacer de substring como --query"
    )


def test_recall_by_unknown_id_fails_closed(monkeypatch, capsys):
    """057b-2: un `--id` inexistente falla CERRADO, no devuelve el corpus entero.

    El modo de fallo que importa: si un id desconocido cayera al recall plano,
    el agente recibiria ruido creyendo que es la leccion que pidio -- un falso
    verde silencioso.

    MUTACION ALCANZABLE: hacer que `--id` desconocido caiga a recall plano ->
    el rc pasa a 0 y el assert cae.
    """
    import scripts.memory_context as memory_context

    monkeypatch.setattr(
        memory_context, "recall_observations", lambda **k: [_obs("algo", topic="x")]
    )
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--recall", "--id", "obs-no-existe"]
    )

    rc = memory_context.main()

    assert rc == 1, "un --id inexistente debe fallar cerrado, no devolver ruido"


def test_recall_ranks_by_similarity_not_corpus_order(monkeypatch, capsys):
    """057b-3: `--query` ordena por RELEVANCIA, no por orden del pool.

    Deuda declarada en 057a: `recall_observations` filtra por substring y
    entrega `filtered[:limit]` en orden de pool. Con `--limit 15` sobre 80 hits,
    CUAL de las lecciones llega era arbitrario -- justo el defecto que
    `find_similar_signals.py` (WOT-2026-039m, IDF + Jaccard) existe para
    resolver, y que llevaba sin cablear a esta puerta.

    Fixture que hace divergir orden-de-pool de relevancia: la entrada MAS
    relevante se coloca la ULTIMA del pool. Sin ranking no entra en el top-1.

    MUTACION ALCANZABLE: quitar el ranking -> gana la primera del pool y cae.
    """
    import scripts.memory_context as memory_context

    ruido = [_obs(f"pipe mencionado de pasada {i}", topic=f"r{i}") for i in range(5)]
    diana = _obs(
        "nunca leas el codigo de salida tras un pipe: mide el ultimo comando "
        "del pipe, no el que te importa",
        topic="pipe-exit-code",
    )
    pool = [*ruido, diana]

    def _fake(query=None, limit=15):
        # RESPETA `limit`, como hace la API real (`filtered[:limit]`). Un mock
        # que lo ignora devuelve el pool entero y el `--limit 1` nunca se
        # ejercita: el test pasaria SIN ranking -- floor assertion.
        return pool[:limit]

    monkeypatch.setattr(memory_context, "recall_observations", _fake)
    monkeypatch.setattr(
        "sys.argv",
        [
            "memory_context.py",
            "--recall",
            "--query",
            "pipe codigo salida",
            "--limit",
            "1",
        ],
    )

    memory_context.main()
    out = capsys.readouterr().out

    assert "pipe-exit-code" in out, (
        "con --limit 1 llego una entrada de relleno en vez de la mas relevante: "
        "el recall entrega en orden de pool, no por similitud"
    )


def test_recall_multiword_query_falls_back_to_ranking(monkeypatch, capsys):
    """057b-4: una consulta de VARIAS palabras no puede devolver cero.

    Medido en la ruta productiva (2026-08-17), y es el defecto que hacia
    inutil el ranking recien cableado:

        --query "suite verde head"  -> 0 hits
        --query "gate que bloquea"  -> 0 hits
        --query "pipe"              -> 16 hits

    `recall_observations` filtra por SUBSTRING LITERAL, asi que una frase solo
    casa si aparece textualmente. El ranking ordena, pero no puede rescatar lo
    que el filtro ya descarto: se ejecutaba sobre una lista vacia.

    Importa justo en el arranque en frio, que es el caso de uso: un agente
    describe su tarea con una FRASE ("la suite quedo stale tras el commit"), no
    con una palabra suelta. Y el prompt de bootstrap ahora manda ejecutar
    `--recall --query <dominio-de-la-tarea>`.

    MUTACION ALCANZABLE: quitar el fallback -> vuelve `No observations found`
    y el assert cae.
    """
    import scripts.memory_context as memory_context

    diana = _obs(
        "REGLA: el discriminante de una suite verde es tested_commit_sha == HEAD",
        topic="suite-sha-head",
    )
    ruido = _obs("algo sobre encoding y BOM", topic="encoding")
    pool = [ruido, diana]

    def _fake(query=None, limit=15):
        # Semantica REAL: substring literal sobre signal/topic/source.
        if query:
            ql = query.lower()
            hits = [
                o
                for o in pool
                if ql in str(o.get("signal", "")).lower()
                or ql in str(o.get("topic", "")).lower()
            ]
        else:
            hits = pool
        return hits[:limit]

    monkeypatch.setattr(memory_context, "recall_observations", _fake)
    monkeypatch.setattr(
        "sys.argv",
        [
            "memory_context.py",
            "--recall",
            "--query",
            "suite verde head",
            "--limit",
            "1",
        ],
    )

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0, "una consulta de varias palabras no puede fallar cerrado"
    assert "suite-sha-head" in out, (
        "el fallback por terminos no encontro la leccion relevante: una frase "
        "solo casa por substring si aparece textualmente, que casi nunca ocurre"
    )


def test_recall_ranking_prefers_coverage_over_brevity(monkeypatch, capsys):
    """057b-5: gana quien cubre MAS terminos de la consulta, no quien es corto.

    Medido en la ruta productiva (2026-08-17) tras cablear el ranker. Con
    `--query "suite verde head"`:

        GANABA   `capturing-rc-after-a-pipe...`  comparte {head}            (20 tokens)
        PERDIA   `suite-green-needs-sha-equals-head`  comparte {suite,verde,head} (90 tokens)

    Causa: Jaccard divide por |consulta UNION documento|, asi que un documento
    LARGO se penaliza por su propia longitud. Nuestro corpus tiene mediana 877
    chars precisamente porque las lecciones son densas: el ranker castigaba la
    virtud del corpus.

    Para RECUPERAR lo que importa no es la similitud simetrica entre dos textos
    (que es para lo que `find_similar_signals` fue escrito -- detectar
    duplicados), sino la COBERTURA de la consulta: cuanto de lo que el agente
    pidio aparece en la leccion. Por eso aqui se pondera por cobertura y el
    empate lo desempata la similitud.

    MUTACION ALCANZABLE: puntuar solo por Jaccard -> gana el documento corto y
    el assert cae.
    """
    import scripts.memory_context as memory_context

    # Proporciones tomadas del caso REAL medido: la ganadora indebida compartia
    # 1 termino con ~20 tokens; la diana compartia 3 con ~90. Un fixture con la
    # densa demasiado corta NO reproduce la penalizacion por longitud y el test
    # pasaria sin la correccion (medido: paso, y hubo que ampliarlo).
    corta = _obs("nota breve sobre head y poco mas", topic="corta-un-termino")
    densa = _obs(
        "REGLA: el discriminante de una suite verde no es el artefacto sino la "
        "igualdad tested_commit_sha == HEAD. " + ("contexto adicional " * 120),
        topic="densa-tres-terminos",
    )
    pool = [corta, densa]

    def _fake(query=None, limit=15):
        # Substring LITERAL, como la API real: la frase entera no casa con nada,
        # asi que se entra por el fallback por terminos. Sin esto el fixture no
        # ejercita el caso que el test dice medir.
        if query:
            ql = query.lower()
            hits = [
                o
                for o in pool
                if ql in str(o.get("signal", "")).lower()
                or ql in str(o.get("topic", "")).lower()
            ]
        else:
            hits = pool
        return hits[:limit]

    monkeypatch.setattr(memory_context, "recall_observations", _fake)
    monkeypatch.setattr(
        "sys.argv",
        [
            "memory_context.py",
            "--recall",
            "--query",
            "suite verde head",
            "--limit",
            "1",
        ],
    )

    memory_context.main()
    out = capsys.readouterr().out

    assert "densa-tres-terminos" in out, (
        "gano la entrada CORTA que cubre 1 termino sobre la DENSA que cubre 3: "
        "el ranker penaliza la longitud, que es justo la virtud de este corpus"
    )


def test_057a_recall_budget_is_tight_not_merely_finite(monkeypatch, capsys):
    """DoD-10: el presupuesto de --recall se mide contra SI MISMO, no contra la entrada.

    Hallazgo BA22: `assert len(out) < 40*3000` era FLOOR ASSERTION con 5x de
    holgura -- un presupuesto de ~30k tokens pasaba verde, que es justo el
    desbordamiento que el ticket dice corregir. El umbral comparaba contra el
    tamaño de la ENTRADA, no contra el presupuesto.

    MUTACION ALCANZABLE: multiplicar `_RECALL_BYTE_BUDGET` por 5 -> el output
    excede el margen y cae.
    """
    budget = 5000
    entradas = [
        {
            "timestamp": "2026-08-17T10:00:00Z",
            "topic": f"t{i}",
            "signal": "Z" * 900,
            "source": "test",
        }
        for i in range(40)
    ]
    monkeypatch.setattr(memory_context, "recall_observations", lambda **k: entradas)
    monkeypatch.setattr(
        "sys.argv",
        ["memory_context.py", "--recall", "--query", "z", "--budget", str(budget)],
    )
    memory_context.main()
    out = capsys.readouterr().out

    cuerpo = out.split("[")[0]
    assert len(cuerpo) <= budget * 1.2, (
        f"el cuerpo emitido ({len(cuerpo)}) desborda el presupuesto ({budget}): "
        "el umbral debe medirse contra el presupuesto, no contra la entrada"
    )


def test_057b_cli_anchors_the_same_root_as_the_hook(tmp_path, monkeypatch, capsys):
    """DoD: el CLI ve la MISMA union que el hook, sin depender de una env var.

    Hallazgo del lector-FS en el bucle L917, y era el peor de la ronda:

        cd <motor>; memory_context.py --recall --id obs-<del-destino>   -> rc=1
        AGENT_PROJECT_ROOT=<destino> ... mismo comando                  -> rc=0

    El mismo id, el mismo comando, dos veredictos OPUESTOS segun una variable
    que ningun prompt mencionaba. Y el mensaje de error afirmaba literalmente
    *"si no aparece, la leccion no esta en este archive"* -- FALSO: si estaba.
    Un falso negativo indistinguible de la verdad, en la puerta que se vendio
    como "exacta y fail-closed".

    Mismo defecto en `--bootstrap`: por CLI daba 207 y por hook 342, asi que el
    fallback documentado para backends SIN hooks (Codex, Kilo) reintroducia
    exactamente la ceguera que este ticket cierra.

    La causa: el hook fijaba `AGENT_PROJECT_ROOT` por su cuenta
    (`_dogfooding_workspace`) y el CLI no hacia nada equivalente.

    MUTACION ALCANZABLE: quitar el anclaje del CLI -> el id del workspace deja
    de resolverse desde el motor y el rc vuelve a 1.
    """
    import scripts.memory_context as memory_context

    motor = tmp_path / "motor"
    ws = tmp_path / "ws"
    (motor / ".agent" / "config").mkdir(parents=True)
    (motor / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    (ws / ".agent" / "config").mkdir(parents=True)
    (ws / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    (motor / ".agent" / "config" / "motor_workspace.txt").write_text(
        "ws\n", encoding="utf-8"
    )
    (ws / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps({"motor_root": str(motor), "destination_root": str(ws)}),
        encoding="utf-8",
    )

    def _entry(oid: str, sig: str) -> str:
        return (
            json.dumps(
                {
                    "id": oid,
                    "timestamp": "2026-07-28T00:00:00+00:00",
                    "topic": oid.replace("obs-", ""),
                    "signal": sig,
                    "source": "test",
                    "source_ticket": "WOT-2026-057b",
                }
            )
            + "\n"
        )

    (motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl").write_text(
        _entry("obs-solo-motor", "leccion del motor"), encoding="utf-8"
    )
    (ws / ".agent/runtime/memory/archive/observations.2026-07.jsonl").write_text(
        _entry("obs-solo-workspace", "leccion del workspace"), encoding="utf-8"
    )

    # `setenv` a un valor controlado y LUEGO `delenv`: el primero registra el
    # valor previo para que monkeypatch lo restaure pase lo que pase. Con solo
    # `delenv`, lo que `_anchor_memory_root` ESCRIBE despues sobrevive al test.
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(ws))
    monkeypatch.delenv("AGENT_PROJECT_ROOT", raising=False)
    # SIN `chdir`: el anclaje resuelve por `_MOTOR_ROOT`, que ya se parchea aqui,
    # asi que cambiar el cwd no aportaba nada al test... y desplazaba el cwd de
    # TODA la sesion de pytest. Medido: `test_scope_gate` resuelve rutas contra
    # el cwd, y con el chdir puesto daba 11 rojos en suite y 32 verdes en
    # aislado -- un state-leak clasico, y de los caros: el sintoma aparece en un
    # fichero que no toque.
    monkeypatch.setattr(memory_context, "_MOTOR_ROOT", motor)
    monkeypatch.setattr(
        "sys.argv", ["memory_context.py", "--recall", "--id", "obs-solo-workspace"]
    )

    rc = memory_context.main()
    out = capsys.readouterr().out

    assert rc == 0, (
        "el CLI no resolvio un id del workspace desde el motor: sin ese anclaje "
        "devuelve rc=1 afirmando que la leccion no existe, y SI existe"
    )
    assert "leccion del workspace" in out
