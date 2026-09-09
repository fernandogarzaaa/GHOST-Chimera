# Ghost Writer extension (developer preview)

Gray ghost completions inside any textarea (Zendesk, Gmail, CRM), served by
your **local** Ghost Chimera console. Completions come from whatever model
provider Ghost has configured — or nothing at all: with no model, the
extension stays completely silent rather than faking suggestions.

## Install (Chrome / Edge, developer mode)

1. Open `chrome://extensions`, enable **Developer mode**.
2. **Load unpacked** → select `extensions/ghost-writer/`.
3. Ensure Ghost Console runs at `http://127.0.0.1:8766`
   (override: `localStorage.ghost_writer_backend = "http://host:port"` on any page).

## Use

- Type in any reply box, pause 1s → gray suggestion appears below the field.
- **Tab** accepts, **Esc** dismisses, click also accepts.
- Backend: `POST /api/stealth/ghost-write {prompt_context}` — same auth as
  the console routes; responses are `{ok, ghost_suggestion, provider}`.

## Privacy

Page text sent to the backend travels only to your localhost Ghost instance,
which forwards the trailing 2,000 characters to your configured model
provider under your existing provider agreement. No keystrokes, no page
contents, and no telemetry ever leave for the extension author.
