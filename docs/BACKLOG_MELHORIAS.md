# Backlog de Melhorias — AutoCommiter

> Baseado no diagnóstico do sistema. Priorização P0 (bloqueia produção) → P1 (segurança/observabilidade) → P2 (produto/pipeline).

---

## P0 — Confiabilidade / Correção (bloqueia ativação em produção)

### P0.1 — Polling → Watchdog com debounce
**File:** `src/autocommiter/service.py:93` (`poll_once`)
**Problema:** Lê SHA256 do arquivo inteiro a cada 5s. Para vault grande causa IO e perde edições rápidas do Obsidian.
**Impacto:** Perda de edições, latência visível no Obsidian, uso desnecessário de CPU/IO.

**Solução:**
- Migrar de polling cíclico para `watchdog` (cross-platform) / `ReadDirectoryChangesW` (Windows) com debounce de 1500–2000ms antes de `service.py:132` `_sync_and_commit`.
- Debounce evita N commits por `Ctrl+S` repetido e respeita `max_detections_per_day`.
- Mantém fallback polling se watchdog indisponível (ex: ambientes sem permissão de filesystem watch).

**Critério de aceite:**
- [ ] Alteração no arquivo detectada em ≤ 2s (com debounce aplicado).
- [ ] Sequência rápida de salvamentos gera **um** commit, não N.
- [ ] `max_detections_per_day` respeitado com watchdog ativo.
- [ ] Fallback funcione com poll 5s se watchdog falhar.

---

### P0.2 — Midnight split-brain (controller.py vs service.py)
**Files:** `service.py:187` (`datetime.now()`) × `controller.py:133` (`date.today()`)
**Problema:** Se cruzar `00:00` entre `active_watched_file` e `today_note_path`, monitora arquivo errado.
**Impacto:** Commit do dia anterior vai para nota do dia seguinte (ou vice-versa) silenciosamente.

**Solução:**
- Injetar **Clock único** (UTC-aware) — `DailyStateStore.load(today)` já centraliza `today`, alinhar ambas as camadas a ele.
- Teste de virada de dia: simular crossover 23:59:59 → 00:00:00 e verificar que `active_watched_file` e `today_note_path` apontam para o mesmo dia lógico.

**Critério de aceite:**
- [ ] `clock.now()` único usado em `service.py` e `controller.py`.
- [ ] Teste `test_midnight_split_brain` passa.
- [ ] Não há commit em nome de `today+1` durante janela de crossover.

---

### P0.3 — `once` sem estado persistente
**File:** `src/autocommiter/cli.py:78`
**Problema:** `initialize() + poll_once` em processo novo nunca detecta mudança pós-reboot (visto em `status`).
**Causa:** fingerprint comparado apenas em memória; dopo reboot/daemon restart nenhum estado persiste.

**Solução:**
- Persistir `last_fingerprint` em `state.json` (ou comparable).
- Comparar `watched_file` vs `mirrored_file_path` (service.py:56) ao invés de confiar apenas em memória.
- Em `initialize`, carregar fingerprint salvo e usar como baseline.

**Critério de aceite:**
- [ ] Após restart, `status` mostra estado correto (detectado/committed) do fingerprint salvo.
- [ ] `state.json` atualizado atomicamente a cada ciclo.

---

### P0.4 — Git staging falso-positivo
**File:** `src/autocommiter/service.py:160` (`has_staged_changes`)
**Problema:** `git diff --cached --quiet` global — se usuário fez `git add` de outro arquivo no mesmo repo, commit inclui lixo.

**Solução:**
- Trocar para `git diff --cached --quiet -- tracked last-event.json` ou `git status --porcelain -- tracked`.
- Verificar apenas o arquivo rastreado, não todo o staging.

**Critério de aceite:**
- [ ] `git add arquivo-aleatorio` em repo vizinho não cola lixo no commit.
- [ ] O último evento JSON é o único verificado.

---

### P0.5 — Background thread bloqueando UI
**File:** `src/autocommiter/gui.py:333` (`_schedule_poll`)
**Problema:** `controller.poll_once()` rodado no Tk mainloop — push lento congela UI.

**Solução:**
- Mover `WatcherService` para `threading.Thread` com `queue.Queue` para `refresh_snapshots`.
- UI só consome snapshots atuais via thread-safe snapshot.

**Critério de aceite:**
- [ ] `poll_once` lento (ex: vault 500MB) não congela mainloop.
- [ ] Refresh de snapshots via queue; UI thread segura.

---

### P0.6 — Interferência em testes / corridas `conftest` × `_write_status`
**Files:** `tests/conftest.py` × `service.py:192` (`_write_status`)
**Problema:** `conftest.py` isolou APPDATA, mas `service.py:192` `_write_status` faz `load()/save()` não-atômicos — corrida se duas instâncias.

**Solução:**
- Tornar `load/save` de state atômico (write para `.tmp` + rename, ou SQLite).
- Em ambiente de teste, duas instâncias concorrentes não corrompem state.

**Critério de aceite:**
- [ ] `test_concurrent_instances` (ou similar) não corrompe state.
- [ ] `state.json` sempre JSON válido apósWrite.

---

## P1 — Segurança / Supply-chain

### P1.1 — Updater sem verificação de integridade
**Files:** `src/autocommiter/updater.py:119` (`download_update`) × `install_asset.py:143`
**Problema:** `pip install --upgrade url.whl` / `Popen(exe/msi)` só com HTTPS — sem SHA256 do release nem assinatura.
**Risco:** MITM/poisoned release silencioso.

**Solução:**
- Usar `payload["assets"].digest` (SHA256) do release.
- `pip install --require-hashes` com hash do wheel, ou verificar binário com `sigstore`/`gpg` antes de executar.

**Critério de aceite:**
- [ ] Instalação só prossegue se hash do asset bater com o esperado.
- [ ] Binários executáveis verificados (sigstore ou hash pré-conhecido).

---

### P1.2 — Registry Run sem validação de caminho
**File:** `src/autocommiter/windows.py:18`
**Problema:** Entrada de registry correta, mas se `.venv` for movido, entrada órfã.

**Solução:**
- `is_autostart_installed` deveria validar `Path(pythonw).exists()` antes de reportar "instalado".

**Critério de aceite:**
- [ ] `is_autostart_installed` falso quando pythonw órfão.
- [ ] Prompt de desinstalação/limpeza oferecido em tela.

---

### P1.3 — `validate_config` não bloqueia symlink fora do repo
**File:** `src/autocommiter/config.py:66`
**Problema:** `is_relative_to` funciona mas não bloqueia symlink que aponta para fora do repo.

**Solução:**
- `strict=True` em `is_relative_to` e revalidar após `resolve()`.

**Critério de aceite:**
- [ ] Config com symlink fora do repo rejeitado.
- [ ] Caminho resolvido validado como subpath do repo.

---

## P1 — Observabilidade / Suporte

### P1.4 — Log em arquivo rotacionado
**File:** `src/autocommiter/cli.py:148`
**Problema:** `logging.basicConfig` só stdout — após crash em segundo plano usuário perde causa raiz.

**Solução:**
- Rotacionar `APPDATA/Logs/autocommiter.log` (RotatingFileHandler, 5MB × 5 backups).
- Expor link/visor no Dashboard.

**Critério de aceite:**
- [ ] Após crash, log com stack trace em `APPDATA/Logs`.
- [ ] Dashboard mostra botão "Ver logs recentes".

---

### P1.5 — Dashboard sem histórico
**File:** `src/autocommiter/gui.py:84`
**Problema:** Mostra só `detected` / `committed_today` — não mostra últimos commits, push failed, limite atingido. `git log --oneline -10` já disponível em status.

**Solução:**
- Incluir painel de últimos 10 commits (`git log --oneline -10`).
- Indicadores: push failed, limite atingido (`max_detections_per_day`), retries.

**Critério de aceite:**
- [ ] Dashboard mostra últimos 10 commits com hash abreviado.
- [ ] Banners para push failed e limite atingido.

---

### P1.6 — Tray icon polui taskbar quando minimizado
**File:** `src/autocommiter/gui.py:52` (`iconify`)
**Problema:** Janela iconificada ainda aparece na taskbar como tarefa separada.

**Solução:**
- Usar `pystray` para tray icon; evitar duplicação na taskbar.

**Critério de aceite:**
- [ ] App minimizada → apenas ícone de tray, sem segunda taskbar entry.

---

## P2 — Produto / UX

### P2.1 — Multi-arquivo (vault/**/*.md)
**Problema:** Hoje 1:1 `watched_file → tracked`. Para Estudos Diários o natural é `vault/**/*.md`.
**Arquivo:** `AppConfig.daily_notes_directory` (Path) → `watch_patterns: list[Path | glob]`.

**Solução:**
- Evoluir config para lista de padrões a observar.
- Novo `watcher.py` suporta múltiplos globs.
- Migração de config.json com fallback para 1:1 se não especificado.

**Critério de aceite:**
- [ ] Configura `watch_patterns: ["vault/**/*.md"]` monitora todos os arquivos.
- [ ] Single-file ainda funciona como padrão quando nenhum pattern dado.

---

### P2.2 — Auto-criar nota do dia via template
**Files:** `controller.py:99` × `service.py:80`
**Problema:** `update_daily_notes_directory` cria `today_note` path mas não o arquivo; `service.py:80` só reporta "not found".

**Solução:**
- Template `templates/daily.md` copiado em `copy-on-first-poll` para o `today_note_path`.
- Se `today_note_path` não existe no primeiro ciclo do dia, criar de template.

**Critério de aceite:**
- [ ] Dia novo → arquivo preenchido com template.
- [ ] Sem overwrite se arquivo existir.

---

### P2.3 — Separar repo de dados do repo do app
**Problema:** Hoje validamos repo = AutoCommiter (self-tracking) e status mostra `??` `.github/` sujo.
**File:** `cli.py:68` (`configure_command`)

**Solução:**
- `configure_command` avisar se `repository_path` contém `pyproject.toml` e sugerir repo privado separado.
- Guia: criar subrepo ou repo separado para tracked-data.

**Critério de aceite:**
- [ ] Aviso claro quando repo suporta ambos (auto-commiter + tracked data).
- [ ] Sugestão de repo separado documentada.

---

### P2.4 — `install.ps1` instala `[dev]` em usuário final
**Files:** `install.ps1:31` × `validate.ps1:18`
**Problema:** Usuário final instala dependencies de dev desnecessários.

**Solução:**
- `install.ps1`: trocar para `pip install -e .` (sem `[dev]`).
- `validate.ps1:18`: instalar `[dev]` só em CI.

**Critério de aceite:**
- [ ] Instalação final não instala `pytest` / `ruff` / `mypy` em ambiente de usuário.

---

## P2 — Pipeline / Distribuição

### P2.5 — CI ausente (`.github/` untracked)
**Problema:** `.github/` untracked — sem CI real.

**Solução:**
- Adicionar GitHub Actions com: `ruff` + `mypy` + `pytest` + `build` em Python 3.11/3.14.
- Impedir merge se APPDATA leak (verificar `.gitignore` e conteúdo do commit).
- Gate de merge: todos os checks passando.

**Critério de aceite:**
- [ ] Workflow `.github/workflows/ci.yml` roda ruff + mypy + pytest + build.
- [ ] PR com arquivo de APPDATA rejeitado pelo check.

---

### P2.6 — Release para updater
**File:** `updater.py:54` (espera `.whl` prioritário)
**Problema:** Falta action para build + `gh release` com `checksums.txt`. Sem isso `update_repository` nunca tem asset.

**Solução:**
- Workflow de release: build wheel, gera `checksums.txt`, cria release com asset.
- Atualização do repositório de update com hash.

**Critério de aceite:**
- [ ] Release contém `.whl` + `checksums.txt`.
- [ ] `updater.py` encontra asset de atualização.

---

### P2.7 — Migração de `config.json` sem `version`
**Problema:** Próxima quebra de schema exige `from_json` com `schema_version` + fallback.

**Solução:**
- Adicionar `schema_version` ao `config.json` e implementar `from_json` com fallback para versões anteriores.

**Critério de aceite:**
- [ ] Leitura de config de versões anteriores não quebra.
- [ ] Versionamento documentado e versionável.

---

## Prioridade de Implementação Sugerida

| Ordem | Ticket | Razão |
| ------ | ------- | ----- |
| 1 | P0.1 (Watchdog) | Bloqueia confiabilidade em produção |
| 2 | P0.2 (Midnight split-brain) | Bug silencioso crítico |
| 3 | P0.3 (once/persistente) | Correção pós-reboot |
| 4 | P0.4 (staging falso-positivo) | Commit sujo |
| 5 | P0.5 (thread UI) | UX quebrada |
| 6 | P0.6 (teste concorrência) | Robustez |
| 7 | P1.1 (updater seguro) | Segurança supply-chain |
| 8 | P1.3 (validate symlink) | Security guard |
| 9 | P2.5 (CI) | Qualidade gate |
| 10 | P2.1 (multi-arquivo) | Produto chave para Estudos Diários |
| — | Demais | P2 catalogados pra postergação |

---

> Documento alive — atualizar conforme tarefas advancem. Links internos: `src/`, `tests/`, `docs/`.
