# Galatiq Case: Invoice Processing Automation

## Configure an LLM key (read first)

The agents in this solution run on a real LLM: xAI Grok (the default) or Anthropic Claude. The case text below says to assume no internet and simulate everything locally; we decided against a simulated model, so offline mode was removed and invoices are processed only when an API key is set. Mock payment and inventory still run locally.

```bash
cp .env.example .env
# then set one key in .env:
XAI_API_KEY=...                                   # Grok (LLM_PROVIDER=grok, the default)
ANTHROPIC_API_KEY=...  and  LLM_PROVIDER=claude   # Claude
```

What a reviewer without a key can still do:

- The CLI's processing commands (`--invoice_path`, `--batch`) stop before creating a run and print "No LLM token provided: set XAI_API_KEY for Grok (in .env or the environment). The app cannot process invoices without it." `--explain`, `review`, and `payments run` still work.
- The web app loads with a "No LLM token provided" banner naming the variable, and uploads are disabled (the API answers 503 `llm_not_configured`). Lists, review decisions, and payments stay usable. `run.sh` and `make dev` start both servers and print the same warning.
- Every test suite runs with no key and no network: the tests use a deterministic fake model that no setting or flag can select.

Network: the backend must reach `api.x.ai` (Grok) or `api.anthropic.com` (Claude) over HTTPS. Behind a firewall or a sandbox proxy, a blocked call comes back as an HTTP 403 from the proxy: allow that host (the 403 body says how), then retry. A blocked or failed call never produces an outcome; the invoice fails closed, and `python main.py --explain <run_id>` shows the error.

## Background

Acme Corp is a PE-backed manufacturing firm losing **$2M/year** on manual invoice processing. Invoices arrive via email as PDFs in messy formats with frequent errors. Staff manually extract data, validate against a legacy inventory database (inconsistent), obtain VP approval (via email chains), and process payment (via a banking API).

**Current pain points:**
- 30% error rate
- 5-day processing delays
- Frustrated stakeholders

## Objective

Build a **multi-agent system** that automates the end-to-end invoice processing workflow. The system must run as a working prototype — not just designs or slides.

## Workflow

The system should handle four stages:

1. **Ingestion** — Extract structured data from invoice documents (PDFs, text files). Fields include: Vendor, Amount, Items (with quantities), and Due Date. Expect unstructured text, typos, missing data, and potentially fraudulent entries.

2. **Validation** — Verify extracted data against a mock inventory database (SQLite). Flag mismatches such as quantity exceeding available stock or items not found in inventory.

3. **Approval** — Simulate VP-level review with rule-based decision-making (e.g., invoices over $10K require additional scrutiny). The agent should reason through approval/rejection with a reflection or critique loop.

4. **Payment** — If approved, call a mock payment function. If rejected, log the rejection with reasoning.

## Technical Requirements

- **LLM Integration**: Use xAI's Grok as the core reasoning engine (via the xAI API at https://grok.x.ai). Other models are acceptable if you don't have an API key.
- **Multi-Agent Orchestration**: Use a framework such as LangGraph, CrewAI, AutoGen, or a custom solution.
- **Agent Capabilities**: Function calling / tool use, structured outputs, and self-correction loops.
- **Runtime**: Assume no internet for external APIs — simulate everything locally.
- **Tech Stack**: Python (preferred), with libraries like `langchain`, `crewai`, `autogen`, `pdfplumber`, `PyMuPDF`, etc. Run locally — no cloud deployment.

## Provided Resources

### Mock Invoice Data

Sample invoices are provided in the `data/invoices/` directory in various formats (PDF, CSV, JSON, TXT). Use these as inputs for testing. The data intentionally includes a mix of clean entries and problematic ones — identifying and handling issues is part of the challenge.

### Mock Inventory Database (Required Setup)

Before running the system, you **must** create a local SQLite database that the validation agent will check invoices against. The sample invoices in `data/invoices/` reference specific items and quantities — your database needs to contain matching inventory records so the validation stage can flag mismatches, out-of-stock items, and unknown products.

Below is a starter schema and seed data that covers the core items referenced across the provided invoices:

```python
import sqlite3

conn = sqlite3.connect('inventory.db')  # Persist to file so all agents can access it
cursor = conn.cursor()

cursor.execute('CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)')
cursor.execute("""
    INSERT INTO inventory VALUES
    ('WidgetA', 15),
    ('WidgetB', 10),
    ('GadgetX', 5),
    ('FakeItem', 0)
""")
conn.commit()
```

**Why this matters:** The sample invoices are designed to test your validation logic against this database. For example:

| Scenario | Invoice | What should happen |
|---|---|---|
| Normal order within stock | INV-1001, INV-1004, INV-1006 | Items found, quantities valid — passes validation |
| Quantity exceeds stock | INV-1002 (requests 20× GadgetX, only 5 in stock) | Flagged as stock mismatch |
| Fraudulent / zero-stock item | INV-1003 (references FakeItem, 0 stock) | Flagged as out of stock or suspicious |
| Item not in database at all | INV-1008 (SuperGizmo, MegaSprocket), INV-1016 (WidgetC) | Flagged as unknown item |
| Invalid data | INV-1009 (negative quantity) | Flagged as data integrity issue |

You may extend the seed data with additional items or columns (e.g., unit price, category) to support richer validation — the above is the minimum needed to exercise the provided test invoices. If you want your system to also validate pricing or vendor information, consider adding tables for those as well.

### Mock Payment API

```python
def mock_payment(vendor, amount):
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}
```

### Grok API Setup

```python
from xai import Grok

client = Grok(api_key="your_key")
response = client.chat.completions.create(
    model="grok-3",
    messages=[{"role": "user", "content": "Reason about this..."}]
)
```

## Running the System

The system should be executable from the command line:

```bash
python main.py --invoice_path=data/invoices/invoice1.txt
```

Output should include structured logs and results.

## Evaluation Criteria

- **Functionality** — Does the system work end-to-end?
- **Code Quality** — Clean, testable, well-structured code with error handling and observability
- **Agentic Sophistication** — LLM integration, multi-agent flow, tool use, self-correction loops
- **Shipping Mindset** — Valuable MVP delivered under ambiguity; scope ruthlessly cut where needed
- **Presentation** — Clear translation of technical decisions to business impact
- **Above/Beyond** - Have you made it your own? Implemented additional features that make the solution feel great? Expanded assumptions? Added to test cases?
- **UI/UX** - Users will understand and enjoy using this system.

## Submission

Submit your solution as a link to a public GitHub repository — GitHub only (github.com).

## CLI usage

Setup is in `backend/README.md`. Run every command from the repo root with the backend venv active. `python -m acme.db seed` creates `acme.db`; the CLI also seeds an empty database on first use. Processing needs an LLM key (see "Configure an LLM key" at the top).

```bash
python main.py --invoice_path=data/invoices/invoice_1001.txt               # one file: stages, findings, outcome, run_id
python main.py --invoice_path=data/invoices/invoice_1002.txt --json        # one JSON object per run on stdout
python main.py --batch data/invoices                                       # every file, sorted by name, results table
python main.py --batch data/invoices --pay                                 # ... then one payment batch
python main.py payments run                                                # pay everything queued now
python main.py payments run --released-by Dana                             # name recorded on the batch (default: cli)
python main.py review                                                      # list invoices awaiting review
python main.py review <run_id> --decision approve --reviewer "Dana" --rationale "Rush pricing agreed by procurement"
python main.py --explain <run_id>                                          # replay a run's audit trail
```

| Flag or command | What it does |
| --- | --- |
| `--invoice_path=<file>` | Process one invoice file. Exits 0 whenever the run reaches an outcome; a missing file exits 1 |
| `--batch <dir>` | Process every supported file (`.pdf .txt .csv .json .xml .eml`) in filename order and write `reports/summary.md` |
| `--provider grok\|claude` | LLM provider for this command only; any other value is rejected. A missing API key stops processing (exit 2) before any run starts |
| `--pay` | Run one payment batch (trigger `pay_all`) after processing |
| `--released-by <name>` | Name recorded on the payment batch, 1 to 50 characters (default `cli`) |
| `--json` | JSON lines on stdout instead of formatted output; logs stay on stderr |
| `--verbose` | Also print INFO-level JSON logs on stderr |
| `--explain <run_id>` | Print the run's trace: extraction attempts, findings with evidence, rules fired, AI VP drafts and Critic responses with provider and model, reviewer decision, disposition |
| `payments run` | Run one payment batch now; prints the batch ID, rows paid, total, and failures |
| `review` | List held invoices with why each is held and the AI recommendation |
| `review <run_id> --decision approve\|reject --reviewer <name> --rationale <text>` | Decide a held invoice (name 1 to 50 characters, rationale at least 15). The same run resumes and continues to disposition |

Approved invoices are queued, never paid by the run itself; only a payment batch calls `mock_payment`. At startup the CLI finishes any interrupted payment batch and, when a key is set, re-runs any invoice left mid-pipeline.

## Web app: ACME Corp IPA

An Angular 18 app (`frontend/`) over the FastAPI backend (`backend/`, see "Web API" in `backend/README.md`). Upload invoices on Home, watch them in the Invoice Queue, decide held ones in Invoice Elevated Review, release payments from the Payment Queue, and check outcomes and reasoning in the Resolution Audit and Payments.

Requirements: Python 3.11+ and Node 20+ (with npm). `uv` is used when present.

```bash
cp .env.example .env        # then add XAI_API_KEY (or ANTHROPIC_API_KEY with LLM_PROVIDER=claude)
make setup                  # backend venv + deps, frontend npm ci, seeds acme.db
make dev                    # FastAPI on :8000 and the web app on http://localhost:4200; Ctrl+C stops both
```

| Make target | What it does |
| --- | --- |
| `make setup` | Creates `backend/.venv`, installs `backend[dev]`, runs `npm ci` in `frontend/`, and seeds `acme.db` |
| `make dev` | Runs uvicorn and `ng serve` together; `ng serve` proxies `/api` to the backend (`frontend/proxy.conf.json`). With no LLM key it prints a warning naming the variable and still starts both |
| `make backend` / `make frontend` | Runs one of the two servers |
| `make test` | Backend pytest suite, then the frontend component tests (headless Chrome) |
| `make e2e` | Playwright end-to-end run: starts its own backend with the test-only fake model (no key, no LLM calls) on a fresh DB and its own dev server, uploads 3 invoices, approves INV-1010, pays all, and checks Payments |

Optional: `docker compose up` runs the same two services in containers, with the provider and keys from `.env` or the environment; open <http://localhost:4200>.

Frontend notes:

- Live data: the app subscribes to `GET /api/events` (Server-Sent Events) and falls back to polling every 3 seconds while the stream is down; polling also pauses while the tab is hidden. The sidebar footer shows "Live" or "Polling".
- Every table shares one component (sort, search, pagination, status chips, row click). Clicking a row opens the invoice detail drawer (`?invoice=<id>`), with the original file beside the extracted fields, findings, and the stage timeline; Back closes it.
- Reviewer and releaser names are typed by hand (1 to 50 characters) and remembered in the browser after the server accepts them. There is no login.
- Component tests: `npm --prefix frontend run test:ci`. Karma uses `CHROME_BIN` or, if unset, Playwright's Chromium (`npx playwright install chromium`).
