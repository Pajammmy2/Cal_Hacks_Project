"""Ember staff planning tool: FastAPI + HTMX + Jinja2, SQLite. Run: python -m ember_staff (binds 127.0.0.1)."""
import hmac
import re
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import card, cartesia, config, db, feed, plan_writer, pregen, profiles, workflow
from .templating import templates

OPEN_PATHS = ("/login", "/static/")

CONSENT_TEXT = ("Your voice will be used only to read {client}'s evacuation plan aloud on their phone. "
                "It is stored by the nonprofit and can be deleted at any time.")

EDITABLE = ("steps_en", "steps_b_en", "shelter_en", "devices_en", "steps_l2", "steps_b_l2", "shelter_l2", "devices_l2")


def create_app():
    app = FastAPI(title="Ember staff tool", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        pw = config.env("EMBER_PASSPHRASE")
        path = request.url.path
        if pw and not path.startswith(OPEN_PATHS) and not request.session.get("ok"):
            if request.headers.get("HX-Request"):
                return Response(status_code=401, headers={"HX-Redirect": "/login"})
            return RedirectResponse("/login?next=" + quote(path), status_code=303)
        return await call_next(request)

    # added after the gate so it wraps it (outermost) and request.session exists inside the gate
    app.add_middleware(SessionMiddleware, secret_key=config.session_secret(), session_cookie="ember_staff",
                       same_site="strict", https_only=False, max_age=12 * 3600)
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

    def page(request, name, **ctx):
        ctx.setdefault("gate_open", not config.env("EMBER_PASSPHRASE"))
        return templates.TemplateResponse(request, name, ctx)

    def must(cid):
        row = db.get(cid)
        if row is None:
            raise _NotFound()
        return row

    class _NotFound(Exception):
        pass

    @app.exception_handler(_NotFound)
    async def nf(request, exc):
        return HTMLResponse("Client not found", status_code=404)

    @app.exception_handler(workflow.Forbidden)
    async def forbidden(request, exc):
        if request.headers.get("HX-Request"):
            # Show the error inside the panel that was clicked (it may be far below #flash), else at the top.
            target = request.headers.get("HX-Target")
            hx = {"HX-Retarget": f"#{target}", "HX-Reswap": "afterbegin"} if target else {"HX-Retarget": "#flash", "HX-Reswap": "innerHTML"}
            return HTMLResponse(f'<p class="err" role="alert">{exc}</p>', status_code=403, headers=hx)
        return HTMLResponse(f"<p>{exc}</p><p><a href='javascript:history.back()'>Back</a></p>", status_code=403)

    # ------------------------------------------------------------ passphrase
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/"):
        return page(request, "login.html", next=next, error=None)

    @app.post("/login")
    def login(request: Request, passphrase: str = Form(""), next: str = Form("/")):
        pw = config.env("EMBER_PASSPHRASE") or ""
        if pw and hmac.compare_digest(passphrase.encode(), pw.encode()):
            request.session["ok"] = True
            return RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
        return page(request, "login.html", next=next, error="That passphrase is not right.")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # ------------------------------------------------------------ 1. clients list
    @app.get("/", response_class=HTMLResponse)
    def clients(request: Request, msg: str = ""):
        f = feed.get_feed()
        rows = db.list_clients()
        for r in rows:
            r["zone_status"] = feed.zone_status(f["situation"], r["profile"].get("zone"))
            r["outage"] = feed.outage_for(f["situation"], r["profile"])
        return page(request, "clients.html", rows=rows, feed=f, feed_age=feed.age_text(f.get("age_s")), msg=msg,
                    card=card, profiles=profiles)

    @app.post("/clients/import")
    async def import_csv(request: Request, file: UploadFile = File(...)):
        text = (await file.read()).decode("utf-8", errors="replace")
        ps, errs = profiles.from_csv(text)
        for p in ps:
            existing = db.get(p["id"]) if p.get("id") else None
            if existing:
                p["voice"] = existing["profile"].get("voice") or p["voice"]
            db.upsert_profile(p)
        msg = f"Imported {len(ps)} clients."
        if errs:
            msg += " Skipped: " + "; ".join(f"line {ln}: {e}" for ln, e in errs[:10])
        return RedirectResponse("/?msg=" + quote(msg), status_code=303)

    @app.post("/clients/run-all")
    def run_all(include_stamped: str = Form("")):
        s = workflow.run_all(include_stamped=bool(include_stamped))
        msg = (f"Ran {s['done']} clients in {s['seconds']} s with templated text"
               f"{'; ' + str(s['failed']) + ' could not be planned' if s['failed'] else ''}"
               f"{'; kept ' + str(s['skipped']) + ' stamped cards' if s['skipped'] else ''}.")
        return RedirectResponse("/?msg=" + quote(msg), status_code=303)

    @app.get("/sample_registry.csv")
    def sample_csv():
        p = config.STAFF_DIR / "sample_registry.csv"
        return Response(p.read_text(), media_type="text/csv")

    # ------------------------------------------------------------ 2. profile
    @app.get("/clients/new", response_class=HTMLResponse)
    def new_client(request: Request):
        return page(request, "profile.html", p=None, form={}, error=None, P=profiles)

    @app.get("/clients/{cid}/edit", response_class=HTMLResponse)
    def edit_client(request: Request, cid: str):
        row = must(cid)
        return page(request, "profile.html", p=row["profile"], form=_form_from_profile(row["profile"]), error=None,
                    P=profiles, plan_error=row.get("plan_error"))

    @app.post("/clients/save")
    async def save_client(request: Request):
        form = dict(await request.form())
        existing = db.get(form.get("id")) if form.get("id") else None
        try:
            p = profiles.from_form(form, existing["profile"] if existing else None)
        except profiles.ProfileError as e:
            return page(request, "profile.html", p=existing["profile"] if existing else None, form=form, error=str(e),
                        P=profiles)
        cid = db.upsert_profile(p)
        row = workflow.run_engine(cid, use_claude=True)
        if row.get("plan_error"):
            return page(request, "profile.html", p=row["profile"], form=_form_from_profile(row["profile"]),
                        error="Saved, but the engine could not plan: " + row["plan_error"], P=profiles)
        return RedirectResponse(f"/clients/{cid}/review", status_code=303)

    @app.post("/clients/{cid}/delete")
    def delete_client(cid: str):
        must(cid)
        notes = workflow.delete_client(cid)
        return RedirectResponse("/?msg=" + quote("Client deleted. " + "; ".join(notes)), status_code=303)

    # ------------------------------------------------------------ 3. review
    def review_ctx(row):
        text = row.get("text") or {}
        if text.get("sections"):
            text = plan_writer.finish(text)   # re-run the deterministic checks so older records get newer ones
        return {"row": row, "p": row["profile"], "plan": row.get("plan"), "text": text, "clips": pregen.samples(row),
                "cardctx": card.context(row) if row.get("plan") else None, "editable": EDITABLE,
                "consent_text": CONSENT_TEXT.format(client=row["profile"]["name"])}

    @app.get("/clients/{cid}/review", response_class=HTMLResponse)
    def review(request: Request, cid: str):
        row = must(cid)
        if not row.get("plan"):
            return RedirectResponse(f"/clients/{cid}/edit", status_code=303)
        return page(request, "review.html", **review_ctx(row))

    @app.get("/clients/{cid}/card", response_class=HTMLResponse)
    def card_html(cid: str, scale: float = 1.0):
        row = must(cid)
        if not row.get("plan"):
            return HTMLResponse("No plan yet.")
        ctx = card.context(row, for_print=False)
        ctx["scale"] = scale
        return HTMLResponse(templates.get_template("card.html").render(**ctx))

    @app.get("/clients/{cid}/panel/{name}", response_class=HTMLResponse)
    def panel(request: Request, cid: str, name: str):
        if name not in ("status", "text", "refuges", "audio"):
            raise _NotFound()
        return page(request, f"_{name}.html", **review_ctx(must(cid)))

    def changed(request, cid, name="text"):
        r = page(request, f"_{name}.html", **review_ctx(must(cid)))
        r.headers["HX-Trigger"] = "cardChanged"
        return r

    @app.get("/clients/{cid}/sentence/{section}/{idx}/edit", response_class=HTMLResponse)
    def sentence_edit(request: Request, cid: str, section: str, idx: int):
        row = must(cid)
        if section not in EDITABLE:
            raise _NotFound()
        value = (row["text"]["sections"].get(section) or [""] * (idx + 1))[idx]
        return page(request, "_sentence_edit.html", row=row, section=section, idx=idx, value=value)

    @app.post("/clients/{cid}/sentence/{section}/{idx}")
    def sentence_save(request: Request, cid: str, section: str, idx: int, value: str = Form(...)):
        must(cid)
        if section not in EDITABLE:
            raise _NotFound()
        try:
            workflow.edit_sentence(cid, section, idx, value)
        except KeyError:
            raise _NotFound()
        return changed(request, cid)

    @app.post("/clients/{cid}/regenerate")
    def regenerate(request: Request, cid: str):
        must(cid)
        workflow.regenerate(cid)
        return changed(request, cid)

    @app.post("/clients/{cid}/swap/{which}")
    def swap(request: Request, cid: str, which: str):
        must(cid)
        if which not in ("a", "b"):
            raise _NotFound()
        workflow.swap(cid, which)
        r = Response(status_code=204)
        r.headers["HX-Refresh"] = "true"
        return r

    @app.post("/clients/{cid}/stamp")
    def stamp(request: Request, cid: str, reviewed_by: str = Form(""), attest: str = Form("")):
        must(cid)
        workflow.stamp(cid, reviewed_by, bool(attest))
        if request.headers.get("HX-Request"):
            return changed(request, cid, "status")
        return RedirectResponse(f"/clients/{cid}/review", status_code=303)

    @app.post("/clients/{cid}/unstamp")
    def unstamp(request: Request, cid: str):
        must(cid)
        db.clear_stamp(cid)
        return changed(request, cid, "status")

    # ------------------------------------------------------------ 4. print
    @app.get("/clients/{cid}/print")
    def print_pdf(cid: str):
        row = must(cid)
        data, pages, level = workflow.print_card(cid)
        safe = "".join(ch for ch in row["profile"]["name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
        return Response(data, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="ember_card_{safe or cid}.pdf"',
                                 "X-Card-Pages": str(pages), "X-Card-Tighten": str(level)})

    # ------------------------------------------------------------ Cartesia audio
    @app.post("/clients/{cid}/audio")
    def audio(request: Request, cid: str):
        row = must(cid)
        if row["status"] not in ("stamped", "printed"):
            raise workflow.Forbidden("Stamp the card before generating audio.")
        if not cartesia.api_key():
            raise workflow.Forbidden("CARTESIA_API_KEY is not set; the phone will use Apple speech for every string.")
        pregen.run_background(cid)
        db.update(cid, audio={"state": "running", "at": db.now()})
        return page(request, "_audio.html", **review_ctx(must(cid)))

    @app.get("/clients/{cid}/audio/clip/{key}")
    def audio_clip(cid: str, key: str):
        row = must(cid)
        if not re.fullmatch(r"[0-9a-f]{40}", key):
            raise _NotFound()
        path = pregen.audio_dir(row)[0] / f"{key}.mp3"
        if not path.exists():
            raise _NotFound()
        return Response(path.read_bytes(), media_type="audio/mpeg")

    @app.get("/clients/{cid}/audio/dry-run")
    def audio_dry_run(cid: str):
        row = must(cid)
        s = pregen.generate(row, dry_run=True)
        s.pop("keys", None)
        return JSONResponse(s)

    # ------------------------------------------------------------ familiar voice (opt-in)
    @app.get("/clients/{cid}/voice", response_class=HTMLResponse)
    def voice_page(request: Request, cid: str):
        row = must(cid)
        return page(request, "voice.html", **review_ctx(row), today=datetime.now().strftime("%B %d, %Y"),
                    has_key=bool(cartesia.api_key()))

    @app.post("/clients/{cid}/voice")
    async def voice_create(request: Request, cid: str, consent_name: str = Form(""), agree: str = Form(""),
                           audio: UploadFile = File(...)):
        row = must(cid)
        if not agree or not consent_name.strip():
            return JSONResponse({"ok": False, "error": "The caregiver must tap \"I agree\" and give their name."}, 400)
        clip = await audio.read()
        if len(clip) < 2000:
            return JSONResponse({"ok": False, "error": "The recording is empty. Record again."}, 400)
        consent = CONSENT_TEXT.format(client=row["profile"]["name"])
        try:
            vid = cartesia.clone_voice(clip, audio.filename or "consent.webm", f"Ember {row['id']} caregiver",
                                       language="en", description=f"Consented caregiver voice for client {row['id']}")
        except cartesia.CartesiaError as e:
            return JSONResponse({"ok": False, "error": f"Could not create the voice: {e}"}, 502)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        p = row["profile"]
        old = p.get("voice") or {}
        p["voice"] = {"kind": "clone", "voice_id": vid, "consent_name": consent_name.strip(), "recorded_at": now,
                      "consent_text": consent, "consent_at": now}
        db.upsert_profile(p)
        if old.get("kind") == "clone" and old.get("voice_id") and old["voice_id"] != vid:
            try:
                cartesia.delete_voice(old["voice_id"])
            except Exception:
                pass
        started = False
        if db.status(db.get(cid)) in ("stamped", "printed"):
            started = pregen.run_background(cid)
        return JSONResponse({"ok": True, "voice_id": vid, "audio_started": started})

    @app.post("/clients/{cid}/voice/delete")
    def voice_delete(cid: str):
        import shutil
        row = must(cid)
        p = row["profile"]
        v = p.get("voice") or {}
        if v.get("voice_id"):
            try:
                cartesia.delete_voice(v["voice_id"])
            except Exception:
                pass
        county = (row.get("plan") or {}).get("county") or config.county()
        shutil.rmtree(config.bundle_dir(county) / "audio" / "clients" / cid, ignore_errors=True)
        p["voice"] = {"kind": "default"}
        db.upsert_profile(p)
        db.clear_stamp(cid)   # the card's "Voice:" line changes
        return RedirectResponse(f"/clients/{cid}/review", status_code=303)

    return app


def _form_from_profile(p):
    f = {k: p.get(k) for k in ("id", "name", "address", "lat", "lon", "zip", "mobility", "transfer", "vision", "hearing",
                               "cognition", "language", "language_other", "zone")}
    for k, v in (p.get("home") or {}).items():
        f[k] = v
    for i, c in enumerate(p.get("contacts") or [], 1):
        f[f"contact{i}_name"] = c.get("name")
        f[f"contact{i}_phone"] = c.get("phone")
        f[f"contact{i}_accessible_vehicle"] = "on" if c.get("accessible_vehicle") else ""
        f[f"contact{i}_distance"] = c.get("distance")
    for d in p.get("devices") or []:
        f[f"dev_{d['kind']}"] = "on"
        if d.get("hours") is not None:
            f[f"dev_{d['kind']}_hours"] = d["hours"]
        if d.get("battery_pct") is not None:
            f["dev_power_chair_battery_pct"] = d["battery_pct"]
    return {k: ("" if v is None else v) for k, v in f.items()}


app = create_app()
