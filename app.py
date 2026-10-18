"""Financer ses études : 15 jours, 15 situations.
Plateforme d'évaluations quotidiennes. Comptes élèves réutilisés de la simulation boursière.
"""
import streamlit as st
import json, hashlib, random, time, os
from datetime import date, datetime, timedelta
from sqlalchemy import text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------- CONFIG ----------------
DATE_DEBUT = date(2026, 10, 19)  # lundi : jour 1
DUREE_MIN = 15                  # minutes par activité
PIN_PROF = "1959"

def jours_activites():
    jours, d = [], DATE_DEBUT
    while len(jours) < 15:
        if d.weekday() < 5:
            jours.append(d)
        d += timedelta(days=1)
    return jours

JOURS = jours_activites()

with open(os.path.join(BASE_DIR, "activites.json"), encoding="utf-8") as f:
    ACTIVITES = {a["jour"]: a for a in json.load(f)["activites"]}

st.set_page_config(page_title="Financer ses études", layout="centered")

# ===== THÈME LE COFFRE =====
with open(os.path.join(BASE_DIR, "style.css"), encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

import streamlit.components.v1 as components

def afficher_minuteur(secondes):
    components.html(f"""
    <div id="min" style="display:inline-block;font-family:'Bebas Neue',sans-serif;
        font-size:1.9rem;letter-spacing:4px;color:#fff;background:#17171b;
        border:1px solid #3d3d44;border-radius:8px;padding:8px 24px;">
        <span style="display:block;font-family:'Work Sans',sans-serif;font-size:0.68rem;
        letter-spacing:3px;color:#9a978f;margin-bottom:2px;">TEMPS ALLOUÉ</span>
        <span id="chrono">--:--</span>
    </div>
    <script>
    var fin = Date.now() + {secondes} * 1000;
    function tick() {{
        var r = Math.max(0, fin - Date.now());
        var m = Math.floor(r / 60000);
        var s = Math.floor((r % 60000) / 1000);
        document.getElementById('chrono').textContent =
            m + ':' + String(s).padStart(2, '0');
        if (r <= 120000) {{
            var el = document.getElementById('min');
            el.style.color = '#E57373';
            el.style.borderColor = '#E57373';
        }}
        if (r > 0) setTimeout(tick, 1000);
    }}
    tick();
    </script>
    """, height=105)

def vault_header():
    st.markdown(
        '<div class="enseigne">'
        '<div class="ligne1">15 jours · 150 points · sans retour</div>'
        '<div class="ligne2">FINANCER <span class="accent">SES <span class="fz">É</span>TUDES</span></div>'
        '</div>'
        '<div class="enseigne-sous"><div class="filet"></div>'
        '<div class="txt">Une évaluation par jour · un seul essai</div></div>',
        unsafe_allow_html=True)

# ---------------- BASE DE DONNÉES ----------------
conn = st.connection("postgres", type="sql")

@st.cache_resource
def init_db():
    with conn.session as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS fq_users (
                username TEXT PRIMARY KEY,
                password TEXT,
                groupe TEXT,
                created_at TEXT
            );"""))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS fq_profils (
                username TEXT, jour INT,
                params TEXT, debut TEXT,
                PRIMARY KEY (username, jour)
            );"""))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS fq_reponses (
                username TEXT, jour INT,
                reponses TEXT, score_auto DOUBLE PRECISION,
                notes_prof TEXT, submitted_at TEXT,
                PRIMARY KEY (username, jour)
            );"""))
        session.commit()

init_db()

def normaliser_nom(nom):
    import unicodedata
    n = unicodedata.normalize("NFKD", nom.strip().lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.replace(" ", ".").replace("'", "").replace("-", ".")
    return ".".join(p for p in n.split(".") if p)

def q(sql, **p):
    return conn.query(sql, params=p, ttl=0)

def q1(sql, **p):
    r = q(sql, **p)
    return r.iloc[0].to_dict() if len(r) else None

def exec_sql(sql, **p):
    with conn.session as session:
        session.execute(text(sql), p)
        session.commit()

# ---------------- PROFIL ALÉATOIRE ----------------
SEL = "financement-2026"

# fonctions sûres autorisées dans les formules de correction
EVAL_NS = {"__builtins__": {}, "max": max, "min": min, "sum": sum,
           "range": range, "round": round, "abs": abs}

def generer_valeur(rng, spec, ctx=None):
    t = spec["type"]
    if t == "int":
        return rng.randint(spec["min"], spec["max"])
    if t == "float":
        return round(rng.uniform(spec["min"], spec["max"]), 2)
    if t == "choix":
        return rng.choice(spec["options"])
    if t == "calcule":
        return eval(spec["formule"], EVAL_NS, dict(ctx or {}))
    raise ValueError(t)

def obtenir_profil(username, jour):
    row = q1("SELECT params FROM fq_profils WHERE username=:u AND jour=:j",
             u=username, j=jour)
    if row:
        return json.loads(row["params"])
    act = ACTIVITES[jour]
    seed = int(hashlib.md5(f"{username}|{jour}|{SEL}".encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    # dossier : généré au jour 1, réutilisé ensuite
    if jour == 1:
        dossier = {}
        for nom, spec in act["variables"].items():
            dossier[nom] = generer_valeur(rng, spec, dossier)
    else:
        d1 = q1("SELECT params FROM fq_profils WHERE username=:u AND jour=1", u=username)
        dossier = json.loads(d1["params"])["dossier"] if d1 else {}
    params = {"dossier": dossier, "vars": {}}
    for nom, spec in act["variables"].items():
        if jour == 1 or spec["type"] == "dossier":
            if spec["type"] == "calcule":
                params["vars"][nom] = generer_valeur(rng, spec, {**dossier, **params["vars"]})
            else:
                params["vars"][nom] = dossier[nom]
        elif spec["type"] == "calcule":
            params["vars"][nom] = generer_valeur(rng, spec, params["vars"])
        else:
            params["vars"][nom] = generer_valeur(rng, spec)
    exec_sql("INSERT INTO fq_profils (username, jour, params, debut) VALUES (:u,:j,:p,'')",
             u=username, j=jour, p=json.dumps(params, ensure_ascii=False))
    return params

def corriger(act, variables, reponses):
    """Retourne (score_auto, detail)."""
    score, detail = 0.0, {}
    for qu in act["questions"]:
        qid = qu["id"]
        rep = reponses.get(qid)
        pts = qu["points"]
        ok = False
        if qu["type"] == "nombre" and rep not in (None, ""):
            try:
                attendu = float(eval(qu["solution"], EVAL_NS, dict(variables)))
                ok = abs(float(rep) - attendu) <= qu.get("tolerance", 1)
            except Exception:
                ok = False
        elif qu["type"] == "choix" and rep not in (None, ""):
            try:
                attendu = eval(str(qu["solution"]), EVAL_NS, dict(variables))
                ok = int(rep) == int(attendu)
            except Exception:
                ok = int(rep) == int(qu["solution"]) if str(qu["solution"]).isdigit() else False
        if ok:
            score += pts
        detail[qid] = {"ok": ok, "pts": pts if ok else 0}
    return score, detail

def compter_mots(t):
    return len(str(t or "").split())

# ---------------- AUTH ----------------
if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    vault_header()
    st.caption("Connecte-toi avec le nom d'utilisateur donné par ton enseignant.")
    u = st.text_input("Nom d'utilisateur (prénom.nom, donné par ton prof)")
    p = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter", use_container_width=True):
        r = q1("SELECT username, password, groupe FROM fq_users WHERE username=:u", u=u.strip().lower())
        if not r:
            st.error("Compte introuvable. Demande ton nom d'utilisateur à ton prof.")
        elif r["password"] is None:
            st.session_state.premier = u.strip().lower()
            st.rerun()
        elif r["password"] == p:
            st.session_state.user = r["username"]
            st.session_state.groupe = r.get("groupe", "")
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    if st.session_state.get("premier"):
        st.divider()
        st.subheader("Première connexion : choisis ton mot de passe")
        n1 = st.text_input("Nouveau mot de passe", type="password", key="n1")
        n2 = st.text_input("Confirme le mot de passe", type="password", key="n2")
        if st.button("Activer mon compte"):
            if not n1 or n1 != n2:
                st.error("Les deux mots de passe doivent être identiques et non vides.")
            else:
                exec_sql("UPDATE fq_users SET password=:p WHERE username=:u",
                         p=n1, u=st.session_state["premier"])
                r = q1("SELECT username, groupe FROM fq_users WHERE username=:u", u=st.session_state["premier"])
                st.session_state.user = r["username"]
                st.session_state.groupe = r.get("groupe", "")
                del st.session_state["premier"]
                st.rerun()
    st.stop()

user = st.session_state.user
est_prof = user.lower() in ("prof", "admin")

# ---------------- VUE PROF ----------------
if est_prof:
    pin = st.text_input("PIN enseignant", type="password") if user.lower() != "prof" else PIN_PROF
    if pin != PIN_PROF:
        if st.button("Quitter"):
            st.session_state.user = None
            st.rerun()
        st.stop()
    st.markdown('<div class="enseigne"><div class="ligne2" style="font-size:2.4rem">SUPERVISION</div></div>'
                '<div class="enseigne-sous"><div class="filet"></div></div>', unsafe_allow_html=True)
    tab_suivi, tab_comptes = st.tabs(["Suivi", "Comptes"])
    eleves = q("SELECT username, groupe FROM fq_users ORDER BY groupe, username")
    with tab_comptes:
        st.subheader("Créer les comptes d'un groupe")
        st.caption("Colle les noms (un par ligne, format Prénom Nom). Les noms d'utilisateur sont générés automatiquement.")
        groupe_in = st.text_input("Groupe (ex. 502)")
        noms_in = st.text_area("Noms des élèves", height=200, key="noms_in")
        if st.button("Créer les comptes"):
            if not groupe_in.strip() or not noms_in.strip():
                st.error("Indique le groupe et au moins un nom.")
            else:
                crees, existants = [], []
                for ligne in noms_in.strip().split("\n"):
                    nom = ligne.strip()
                    if not nom:
                        continue
                    base = normaliser_nom(nom)
                    username = base
                    k = 2
                    while q1("SELECT username FROM fq_users WHERE username=:u", u=username):
                        username = f"{base}{k}"
                        k += 1
                    if q1("SELECT username FROM fq_users WHERE username=:u", u=base):
                        existants.append(nom)
                    exec_sql("INSERT INTO fq_users (username, password, groupe, created_at) VALUES (:u, NULL, :g, :t)",
                             u=username, g=groupe_in.strip(),
                             t=datetime.now().isoformat(timespec="seconds"))
                    crees.append(f"{nom} → {username}")
                st.success(f"{len(crees)} comptes créés.")
                for c in crees:
                    st.write(c)
        st.divider()
        st.subheader("Comptes existants")
        if len(eleves):
            st.dataframe(eleves, use_container_width=True, hide_index=True)
            asuppr = st.selectbox("Supprimer un compte", [""] + eleves["username"].tolist())
            if asuppr and st.button("Supprimer définitivement"):
                exec_sql("DELETE FROM fq_reponses WHERE username=:u", u=asuppr)
                exec_sql("DELETE FROM fq_profils WHERE username=:u", u=asuppr)
                exec_sql("DELETE FROM fq_users WHERE username=:u", u=asuppr)
                st.success("Supprimé.")
                st.rerun()
    with tab_suivi:
        groupes = sorted(eleves["groupe"].dropna().unique().tolist()) if len(eleves) else []
        gsel = st.selectbox("Groupe", ["Tous"] + groupes)
        el = eleves if gsel == "Tous" else eleves[eleves["groupe"] == gsel]
        import pandas as pd
        reps = q("SELECT username, jour, score_auto, notes_prof, submitted_at FROM fq_reponses")
        def note_totale(r):
            tot = float(r["score_auto"] or 0)
            try:
                np_ = json.loads(r["notes_prof"] or "{}")
                tot += sum(float(v) for v in np_.values())
            except Exception:
                pass
            return tot
        grid = []
        for _, e in el.iterrows():
            ligne = {"Élève": e["username"], "Groupe": e["groupe"]}
            tot = 0
            for j in range(1, 16):
                rr = reps[(reps["username"] == e["username"]) & (reps["jour"] == j)]
                if len(rr):
                    n = note_totale(rr.iloc[0].to_dict())
                    ligne[f"J{j}"] = round(n, 1)
                    tot += n
                else:
                    ligne[f"J{j}"] = "–"
            ligne["Total /150"] = round(tot, 1)
            grid.append(ligne)
        st.dataframe(pd.DataFrame(grid), use_container_width=True, hide_index=True)
    if st.button("Quitter"):
        st.session_state.user = None
        st.rerun()
    st.stop()

# ---------------- VUE ÉLÈVE ----------------
vault_header()
aujourdhui = date.today()
is_test = st.session_state.get("groupe") == "TEST"

# jour strict : seul le jour calendaire d'aujourd'hui est jouable
jour_courant = None
for i, d in enumerate(JOURS, start=1):
    if d == aujourdhui:
        jour_courant = i
        break

def statut_jour(i):
    fait = q1("SELECT submitted_at FROM fq_reponses WHERE username=:u AND jour=:j", u=user, j=i)
    if fait:
        return "fait"
    if JOURS[i - 1] < aujourdhui:
        return "manque"
    if JOURS[i - 1] == aujourdhui:
        return "aujourdhui"
    return "verrouille"

def afficher_termine(i):
    st.success("Terminé. Aucun retour en arrière possible.")
    r = q1("SELECT score_auto, notes_prof, reponses FROM fq_reponses WHERE username=:u AND jour=:j", u=user, j=i)
    tot = float(r["score_auto"] or 0)
    try:
        tot += sum(float(v) for v in json.loads(r["notes_prof"] or "{}").values())
    except Exception:
        pass
    st.metric("Note", f"{tot:.1f} / 10")
    with st.expander("Revoir mes réponses"):
        act = ACTIVITES[i]
        pr = q1("SELECT params FROM fq_profils WHERE username=:u AND jour=:j", u=user, j=i)
        variables = json.loads(pr["params"])["vars"] if pr else {}
        rep = json.loads(r["reponses"] or "{}")
        for qu in act["questions"]:
            st.markdown(f"**{qu['enonce']}**")
            v = rep.get(qu["id"])
            if qu["type"] == "choix":
                try:
                    opts_fmt = [o.format(**variables) for o in qu["options"]]
                except KeyError:
                    opts_fmt = qu["options"]
                st.write(f"Ta réponse : {opts_fmt[int(v)] if v is not None else '—'}")
                try:
                    att = opts_fmt[int(float(eval(str(qu['solution']), EVAL_NS, dict(variables))))]
                    st.write(f"Bonne réponse : {att}")
                except Exception:
                    pass
            elif qu["type"] == "nombre":
                st.write(f"Ta réponse : {v if v is not None else '—'}")
                try:
                    att = round(float(eval(qu["solution"], EVAL_NS, dict(variables))), 2)
                    st.write(f"Bonne réponse : {att}")
                except Exception:
                    pass
            else:
                st.write(v or "—")

def afficher_activite(i):
    act = ACTIVITES[i]
    profil = obtenir_profil(user, i)
    variables = profil["vars"]
    try:
        histoire = act["histoire"].format(**variables)
    except KeyError:
        histoire = act["histoire"]
    st.subheader(f"Évaluation {i} : {act['titre']}")
    st.caption(f"À compléter aujourd'hui · {DUREE_MIN} minutes · un seul envoi définitif")
    st.markdown(f'<div class="situation"><div class="sit-titre">Mise en situation</div>'
                f'<div class="sit-texte">{histoire}</div></div>', unsafe_allow_html=True)
    if "debut" not in st.session_state or st.session_state.get("jour_minuteur") != i:
        st.session_state.debut = time.time()
        st.session_state.jour_minuteur = i
    reste = DUREE_MIN * 60 - (time.time() - st.session_state.debut)
    afficher_minuteur(max(0, int(reste)))
    with st.form(f"form_{i}"):
        reponses = {}
        for nq, qu in enumerate(act["questions"], start=1):
            st.markdown('<div class="q-bloc">', unsafe_allow_html=True)
            st.markdown(f'<div class="q-head"><span class="q-num">Question {nq}</span>'
                        f'<span class="q-pts">· {qu["points"]} points</span></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="q-enonce">{qu["enonce"]}</div>', unsafe_allow_html=True)
            if qu["type"] == "nombre":
                reponses[qu["id"]] = st.number_input("Ta réponse", value=None, key=f"{i}_{qu['id']}", format="%.2f")
            elif qu["type"] == "choix":
                try:
                    opts_fmt = [o.format(**variables) for o in qu["options"]]
                except KeyError:
                    opts_fmt = qu["options"]
                reponses[qu["id"]] = st.radio("Choisis", options=list(range(len(opts_fmt))),
                                             format_func=lambda x, o=opts_fmt: o[x], key=f"{i}_{qu['id']}")
            else:
                reponses[qu["id"]] = st.text_area("Ta réponse", key=f"{i}_{qu['id']}")
            st.markdown('</div>', unsafe_allow_html=True)
        envoyer = st.form_submit_button("Soumettre mes réponses", use_container_width=True)
    if envoyer:
        if q1("SELECT submitted_at FROM fq_reponses WHERE username=:u AND jour=:j", u=user, j=i):
            st.warning("Réponse déjà envoyée.")
            st.stop()
        for qu in act["questions"]:
            if qu["type"] == "texte" and compter_mots(reponses.get(qu["id"])) < qu["min_mots"]:
                st.error(f"Question texte : écris au moins {qu['min_mots']} mots (tu en as {compter_mots(reponses.get(qu['id']))}).")
                st.stop()
        rep_json = {}
        for qu in act["questions"]:
            v = reponses.get(qu["id"])
            rep_json[qu["id"]] = None if v is None else (v if qu["type"] != "nombre" else float(v))
        score_auto, detail = corriger(act, variables, rep_json)
        exec_sql("""INSERT INTO fq_reponses (username, jour, reponses, score_auto, notes_prof, submitted_at)
                    VALUES (:u,:j,:r,:s,'{}',:t)""",
                 u=user, j=i, r=json.dumps(rep_json, ensure_ascii=False), s=score_auto,
                 t=datetime.now().isoformat(timespec="seconds"))
        st.success("Envoyé. C'est verrouillé.")
        for qu in act["questions"]:
            if qu["type"] == "texte":
                continue
            d_ = detail[qu["id"]]
            if d_["ok"]:
                st.write(f"✓ {qu['id']} : bonne réponse ({d_['pts']} pts)")
            else:
                try:
                    att = eval(qu["solution"], EVAL_NS, dict(variables))
                    if qu["type"] == "choix":
                        try:
                            opts_fmt = [o.format(**variables) for o in qu["options"]]
                        except KeyError:
                            opts_fmt = qu["options"]
                        att = opts_fmt[int(float(att))]
                    st.write(f"✗ {qu['id']} : raté (bonne réponse : {att})")
                except Exception:
                    st.write(f"✗ {qu['id']} : raté")
        st.write(f"**Score : {score_auto:.1f} / 10**")
        if "debut" in st.session_state:
            del st.session_state["debut"]
        st.rerun()

def afficher_progression():
    st.subheader("Mon parcours")
    reps = q("SELECT score_auto FROM fq_reponses WHERE username=:u", u=user)
    total = round(sum(float(r["score_auto"] or 0) for _, r in reps.iterrows()), 1)
    pct = min(100, total / 150 * 100)
    st.markdown(
        f'<div class="progression"><div class="prog-tete">'
        f'<span class="prog-label">Cagnotte</span>'
        f'<span class="prog-chiffre">{total} / 150</span></div>'
        f'<div class="prog-piste"><div class="prog-remplissage" style="width:{pct}%"></div></div></div>',
        unsafe_allow_html=True)
    lib = {"fait": "Complété", "manque": "Manqué", "aujourdhui": "Aujourd'hui", "verrouille": "À venir"}
    cartes = []
    for i in range(1, 16):
        s = statut_jour(i)
        d = JOURS[i - 1].strftime("%d/%m")
        cartes.append(
            f'<div class="jour-carte {s}"><div class="jnum">{i:02d}</div>'
            f'<div class="jdate">{d}</div><div class="jstat">{lib[s]}</div></div>')
    st.markdown('<div class="jours-grille">' + "".join(cartes) + '</div>', unsafe_allow_html=True)
    st.divider()

if is_test:
    st.caption("Mode test : tous les jours accessibles.")
    onglets = st.tabs([f"J{i}" for i in range(1, 16)])
    for i in range(1, 16):
        with onglets[i - 1]:
            if statut_jour(i) == "fait":
                afficher_termine(i)
            else:
                afficher_activite(i)
else:
    afficher_progression()
    if jour_courant is None:
        st.info("Aucune activité aujourd'hui. Reviens un jour d'école.")
    elif statut_jour(jour_courant) == "fait":
        afficher_termine(jour_courant)
    else:
        afficher_activite(jour_courant)

st.sidebar.write(f"Connecté : {user}")
if st.sidebar.button("Quitter"):
    st.session_state.user = None
    st.rerun()
