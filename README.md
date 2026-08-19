# HSC Match Bridge

Adapter/runtime independente entre o HSC Central Match Domain e instâncias locais CS2 / MatchZy.

## Papel

```text
Central Match Domain
        ↓ HTTPS outbound
HSC Match Bridge
        ↓ filesystem + RCON
CS2 / MatchZy
```

Um processo corresponde a um `bridgeNodeKey` e pode gerenciar um ou mais `serverKey`.

## Fronteiras

O Bridge:

- não acessa MariaDB Central;
- não usa RabbitMQ;
- não depende do Match Edge para preparação;
- não expõe listener HTTP público;
- não recebe autoridade por `bridgeNodeKey` enviado pelo client;
- não guarda RCON password no registry.

## G1 — protocolo Central

Implementado:

- heartbeat;
- claim;
- lease;
- result;
- credential dedicada;
- Match Spec v1;
- journal local SQLite.

## G2 — MatchZy Adapter

Implementado:

- renderer determinístico;
- registry schema v2;
- materialização atômica;
- external `gorcon/rcon-cli`;
- `matchzy_loadmatch`;
- strong PREPARED verifier;
- reconciliação de `APPLYING`.

Journal:

```text
RECEIVED
→ APPLYING
→ SUCCEEDED | FAILED
```

`APPLYING` representa execução incerta e nunca é reexecutado cegamente.

## Strong PREPARED

A preparação é considerada forte apenas quando:

- MatchZyPlayerNames contém exatamente os 10 SteamIDs esperados;
- `status_json.server.map` corresponde ao mapa;
- `get5_status.matchid` corresponde ao runtime ID;
- `loaded_config_file` é o arquivo esperado;
- gamestate não é `none`;
- Team A/B correspondem ao spec.

## G3 — daemon e produção

Implementado:

- processo persistente;
- heartbeat imediato + periódico;
- polling contínuo;
- backoff bounded;
- SIGTERM/SIGINT graceful;
- systemd;
- configuração produtiva;
- registry produtivo;
- daemon Hostinger.

Target inicial validado:

```text
bridgeNodeKey = hsc-cs2-hostinger-01
serverKey = hsc-mix-01
```

## Acceptance real

O fluxo abaixo foi validado em produção:

```text
READY
→ ServerAssignment
→ PREPARE_MATCH
→ Bridge
→ MatchZy
→ PREPARED
```

Com `runtime_match_id=1000000`.

O fixture foi revertido depois e o runtime terminou idle.

## Boundary atual

O Bridge não implementa:

- JOINABLE;
- join authorization;
- IN_GAME;
- FINISHED;
- series_end;
- assignment release;
- reset lifecycle completo.

Essas responsabilidades serão coordenadas em slices futuras entre Central / Match Edge / Bridge.

## CLI

Validação local sem network:

```bash
hsc-match-bridge check
```

Daemon:

```bash
hsc-match-bridge run
```

## Produção

Target suportado atual:

```text
Hostinger VPS / Debian 13
systemd
User=amp
Group=amp
```

Runbook detalhado deve continuar em `docs/`, não neste README.

## Segurança

Nunca exibir:

- raw Bridge credential;
- RCON password;
- SSH keys.

Registry contém apenas paths e logical server keys.