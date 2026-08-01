"""
Validation script — run with: py ai_mentor/_validate.py
Checks app factory boot, blueprint registration, URL rules, and template existence.
"""
import sys
import os

# Put the package root on the path
sys.path.insert(0, os.path.dirname(__file__))

PASS = []
FAIL = []

def check(label, ok, detail=""):
    if ok:
        PASS.append(label)
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL.append(label)
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


# ── 1. App factory ──────────────────────────────────────────────────────────
print("\n=== 1. App Factory Boot ===")
try:
    from app import create_app
    app = create_app()
    check("create_app() returns Flask instance", app is not None)
    check("SECRET_KEY set",        bool(app.config.get("SECRET_KEY")))
    check("DB URI configured",     bool(app.config.get("SQLALCHEMY_DATABASE_URI")), app.config["SQLALCHEMY_DATABASE_URI"])
    check("WATSONX_URL present",   bool(app.config.get("WATSONX_URL")),   app.config["WATSONX_URL"])
    check("WATSONX_MODEL_ID set",  bool(app.config.get("WATSONX_MODEL_ID")), app.config["WATSONX_MODEL_ID"])
    check("AI_MAX_TOKENS numeric", isinstance(app.config.get("AI_MAX_TOKENS"), int), str(app.config.get("AI_MAX_TOKENS")))
    check("MENTOR_NAME set",       bool(app.config.get("MENTOR_NAME")), app.config["MENTOR_NAME"])
except Exception as e:
    check("create_app()", False, str(e))
    print("\nFATAL: cannot continue without working app factory.")
    sys.exit(1)

# ── 2. Blueprints ────────────────────────────────────────────────────────────
print("\n=== 2. Blueprint Registration ===")
expected_blueprints = {"auth", "mentor", "dashboard"}
# Derive actual prefixes from url_map (Blueprint.url_prefix is None when set at register time)
prefix_map = {}
for rule in app.url_map.iter_rules():
    parts = rule.rule.split("/")
    if len(parts) >= 2 and parts[1]:
        prefix_map.setdefault(parts[1], rule.endpoint.split(".")[0])
for name in expected_blueprints:
    bp = app.blueprints.get(name)
    registered = bp is not None
    has_routes  = any(r.endpoint.startswith(f"{name}.") for r in app.url_map.iter_rules())
    check(f"blueprint '{name}' registered", registered and has_routes,
          f"blueprint={'found' if registered else 'missing'}, routes={'found' if has_routes else 'none'}")

# ── 3. URL Rules ─────────────────────────────────────────────────────────────
print("\n=== 3. URL Rules ===")
expected_routes = [
    "/auth/login",
    "/auth/register",
    "/auth/logout",
    "/dashboard/",
    "/dashboard/new",
    "/dashboard/delete/<int:session_id>",
    "/mentor/chat/<int:session_id>",
    "/mentor/chat/<int:session_id>/send",
    "/mentor/chat/<int:session_id>/stage",
]
actual_rules = {r.rule for r in app.url_map.iter_rules()}
for route in expected_routes:
    check(f"route '{route}'", route in actual_rules)

# ── 4. Templates ─────────────────────────────────────────────────────────────
print("\n=== 4. Template Existence ===")
template_dir = os.path.join(os.path.dirname(__file__), "templates")
expected_templates = [
    "base.html",
    "auth/login.html",
    "auth/register.html",
    "dashboard/index.html",
    "mentor/chat.html",
]
for tpl in expected_templates:
    path = os.path.join(template_dir, tpl)
    check(f"template '{tpl}'", os.path.isfile(path))

# ── 5. Static assets ────────────────────────────────────────────────────────
print("\n=== 5. Static Assets ===")
static_dir = os.path.join(os.path.dirname(__file__), "static")
expected_static = [
    "css/main.css",
    "js/main.js",
    "js/chat.js",
]
for asset in expected_static:
    path = os.path.join(static_dir, asset)
    check(f"static '{asset}'", os.path.isfile(path))

# ── 6. DB tables can be created ─────────────────────────────────────────────
print("\n=== 6. Database Table Creation (SQLite in-memory) ===")
try:
    from config import TestingConfig
    test_app = create_app(TestingConfig)
    with test_app.app_context():
        from extensions import db
        db.create_all()
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        for table in ("users", "mentor_sessions", "messages"):
            exists = table in inspector.get_table_names()
            check(f"table '{table}' created", exists)
        db.drop_all()
except Exception as e:
    check("db.create_all()", False, str(e))

# ── 7. AIService structure ───────────────────────────────────────────────────
print("\n=== 7. AIService Internal Checks ===")
try:
    from services.ai_service import AIService, SECTION_LABELS
    svc = AIService()
    check("AIService instantiates",         True)
    check("get_response method present",    callable(getattr(svc, "get_response", None)))
    check("_build_prompt method present",   callable(getattr(svc, "_build_prompt", None)))
    check("_format_response method present",callable(getattr(svc, "_format_response", None)))
    check("ANALYSIS_INSTRUCTION non-empty", bool(svc.ANALYSIS_INSTRUCTION))
    check("FOLLOWUP_INSTRUCTION non-empty", bool(svc.FOLLOWUP_INSTRUCTION))
    check("STAGE_HINTS has ideation",       "ideation"  in svc.STAGE_HINTS)
    check("STAGE_HINTS has prototype",      "prototype" in svc.STAGE_HINTS)
    check("STAGE_HINTS has scale",          "scale"     in svc.STAGE_HINTS)
    check("SECTION_LABELS has 5 entries",   len(SECTION_LABELS) == 5)

    # _build_prompt smoke test (no network call)
    history = [{"role": "user", "content": "I want to build an AI chatbot."}]
    prompt = svc._build_prompt(svc.ANALYSIS_INSTRUCTION, svc.STAGE_HINTS["ideation"], history)
    check("_build_prompt returns string",   isinstance(prompt, str))
    check("_build_prompt ends with 'Aria:'", prompt.strip().endswith("Aria:"))
    check("prompt contains user message",   "I want to build an AI chatbot." in prompt)

    # _format_response smoke test
    structured = (
        "PROBLEM IDENTIFICATION: Lack of 24/7 support.\n"
        "TECHNOLOGY SUGGESTIONS: Watson Assistant, NLP.\n"
        "REQUIRED COMPONENTS: UI, backend, DB.\n"
        "INNOVATION IMPROVEMENTS: Voice support.\n"
        "DEVELOPMENT ROADMAP: Phase 1 MVP."
    )
    formatted = svc._format_response(structured)
    check("_format_response detects sections",   "▸" in formatted)
    check("_format_response passthrough on plain", svc._format_response("Hello!") == "Hello!")
except Exception as e:
    check("AIService checks", False, str(e))

# ── 8. watsonx.ai config validation ─────────────────────────────────────────
print("\n=== 8. watsonx.ai Config Validation ===")
with app.app_context():
    cfg = app.config
    check("WATSONX_API_KEY key exists in config",    "WATSONX_API_KEY"    in cfg)
    check("WATSONX_PROJECT_ID key exists in config", "WATSONX_PROJECT_ID" in cfg)
    check("WATSONX_URL key exists in config",        "WATSONX_URL"        in cfg)
    check("WATSONX_MODEL_ID key exists in config",   "WATSONX_MODEL_ID"   in cfg)
    # Warn (not fail) if credentials are placeholder values
    api_key = cfg.get("WATSONX_API_KEY", "")
    project_id = cfg.get("WATSONX_PROJECT_ID", "")
    if not api_key:
        print("  WARN  WATSONX_API_KEY is empty — set it in .env before running")
    if not project_id:
        print("  WARN  WATSONX_PROJECT_ID is empty — set it in .env before running")

# ── Summary ──────────────────────────────────────────────────────────────────
total = len(PASS) + len(FAIL)
print(f"\n{'='*50}")
print(f"RESULT: {len(PASS)}/{total} checks passed")
if FAIL:
    print(f"\nFailed checks:")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed. Project is ready.")
    sys.exit(0)
