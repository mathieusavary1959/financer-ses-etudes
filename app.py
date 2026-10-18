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

def generer_valeur(rng, spec):
    t = spec["type"]
    if t == "int":
        return rng.randint(spec["min"], spec["max"])
    if t == "float":
        return round(rng.uniform(spec["min"], spec["max"]), 2)
    if t == "choix":
        return rng.choice(spec["options"])
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
            dossier[nom] = generer_valeur(rng, spec)
    else:
        d1 = q1("SELECT params FROM fq_profils WHERE username=:u AND jour=1", u=username)
        dossier = json.loads(d1["params"])["dossier"] if d1 else {}
    params = {"dossier": dossier, "vars": {}}
    for nom, spec in act["variables"].items():
        if jour == 1 or spec["type"] == "dossier":
            params["vars"][nom] = dossier[nom]
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
                attendu = float(eval(qu["solution"], {"__builtins__": {}}, dict(variables)))
                ok = abs(float(rep) - attendu) <= qu.get("tolerance", 1)
            except Exception:
                ok = False
        elif qu["type"] == "choix" and rep not in (None, ""):
            try:
                attendu = eval(str(qu["solution"]), {"__builtins__": {}}, dict(variables))
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
    st.title("Financer ses études")
    st.caption("15 jours, 15 situations. Une par jour, sans retour en arrière.")
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
    st.title("Supervision : Financer ses études")
    tab_suivi, tab_corriger, tab_comptes = st.tabs(["Suivi", "Corriger les textes", "Comptes"])
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
    with tab_corriger:
        st.subheader("Corriger les textes")
        if len(eleves):
            eu = st.selectbox("Élève", eleves["username"].tolist())
            ej = st.selectbox("Jour", list(range(1, 16)))
            r = q1("SELECT reponses, score_auto, notes_prof FROM fq_reponses WHERE username=:u AND jour=:j", u=eu, j=ej)
            if not r:
                st.info("Pas encore fait.")
            else:
                act = ACTIVITES[ej]
                pr = q1("SELECT params FROM fq_profils WHERE username=:u AND jour=:j", u=eu, j=ej)
                variables = json.loads(pr["params"])["vars"] if pr else {}
                st.markdown(act["histoire"].format(**{k: v for k, v in variables.items() if k in act["histoire"]}))
                rep = json.loads(r["reponses"])
                notes = json.loads(r["notes_prof"] or "{}")
                for qu in act["questions"]:
                    if qu["type"] != "texte":
                        continue
                    st.markdown(f"**{qu['enonce']}**")
                    st.info(rep.get(qu["id"], ""))
                    nv = st.number_input(f"Note / {qu['points']}", 0.0, float(qu["points"]),
                                         float(notes.get(qu["id"], 0)), step=0.5, key=f"n_{eu}_{ej}_{qu['id']}")
                    notes[qu["id"]] = nv
                if st.button("Enregistrer les notes"):
                    exec_sql("UPDATE fq_reponses SET notes_prof=:n WHERE username=:u AND jour=:j",
                             n=json.dumps(notes), u=eu, j=ej)
                    st.success("Enregistré.")
    if st.button("Quitter"):
        st.session_state.user = None
        st.rerun()
    st.stop()

# ---------------- VUE ÉLÈVE ----------------
st.title("Financer ses études")
aujourdhui = date.today()
jour_debloque = 0
for i, d in enumerate(JOURS, start=1):
    if d <= aujourdhui:
        jour_debloque = i
if st.session_state.get("groupe") == "TEST":
    jour_debloque = 15  # compte test : tout débloqué

onglets = st.tabs([f"Jour {i}" for i in range(1, 16)])
for i in range(1, 16):
    with onglets[i - 1]:
        d = JOURS[i - 1]
        fait = q1("SELECT submitted_at FROM fq_reponses WHERE username=:u AND jour=:j", u=user, j=i)
        if i > jour_debloque:
            st.info(f"Ce jour se débloque le {d.strftime('%d/%m/%Y')}.")
            continue
        if fait:
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
                        st.write(f"Ta réponse : {qu['options'][int(v)] if v is not None else '—'}")
                        try:
                            att = qu["options"][int(float(eval(str(qu['solution']), {'__builtins__': {}}, dict(variables))))]
                            st.write(f"Bonne réponse : {att}")
                        except Exception:
                            pass
                    elif qu["type"] == "nombre":
                        st.write(f"Ta réponse : {v if v is not None else '—'}")
                        try:
                            att = round(float(eval(qu["solution"], {"__builtins__": {}}, dict(variables))), 2)
                            st.write(f"Bonne réponse : {att}")
                        except Exception:
                            pass
                    else:
                        st.write(v or "—")
            continue
        # activité du jour
        act = ACTIVITES[i]
        profil = obtenir_profil(user, i)
        variables = profil["vars"]
        try:
            histoire = act["histoire"].format(**variables)
        except KeyError:
            histoire = act["histoire"]
        st.subheader(f"Jour {i} : {act['titre']}")
        st.write(histoire)
        # minuteur
        if "debut" not in st.session_state or st.session_state.get("jour_minuteur") != i:
            st.session_state.debut = time.time()
            st.session_state.jour_minuteur = i
        reste = DUREE_MIN * 60 - (time.time() - st.session_state.debut)
        if reste <= 0:
            st.error("Temps écoulé. Tu dois terminer avec ce que tu as.")
            reste = 0
        else:
            st.caption(f"Temps restant : {int(reste // 60)} min {int(reste % 60)} s")
        with st.form(f"form_{i}"):
            reponses = {}
            for qu in act["questions"]:
                st.markdown(f"**{qu['enonce']}**")
                if qu["type"] == "nombre":
                    reponses[qu["id"]] = st.number_input("Ta réponse", value=None, key=f"{i}_{qu['id']}", format="%.2f")
                elif qu["type"] == "choix":
                    reponses[qu["id"]] = st.radio("Choisis", options=list(range(len(qu["options"]))),
                                                 format_func=lambda x: qu["options"][x], key=f"{i}_{qu['id']}")
                else:
                    reponses[qu["id"]] = st.text_area("Ta réponse", key=f"{i}_{qu['id']}")
            envoyer = st.form_submit_button("Envoyer (définitif)", use_container_width=True)
        if envoyer:
            # sécurité : déjà envoyé ? (double-clic)
            if q1("SELECT submitted_at FROM fq_reponses WHERE username=:u AND jour=:j", u=user, j=i):
                st.warning("Réponse déjà envoyée.")
                st.stop()
            # vérif longueur textes
            for qu in act["questions"]:
                if qu["type"] == "texte" and compter_mots(reponses.get(qu["id"])) < qu["min_mots"]:
                    st.error(f"Question texte : écris au moins {qu['min_mots']} mots (tu en as {compter_mots(reponses.get(qu['id']))}).")
                    st.stop()
            # normaliser
            rep_json = {}
            for qu in act["questions"]:
                v = reponses.get(qu["id"])
                rep_json[qu["id"]] = None if v is None else (v if qu["type"] != "nombre" else float(v))
            score_auto, detail = corriger(act, variables, rep_json)
            exec_sql("""INSERT INTO fq_reponses (username, jour, reponses, score_auto, notes_prof, submitted_at)
                        VALUES (:u,:j,:r,:s,'{}',:t)""",
                     u=user, j=i, r=json.dumps(rep_json, ensure_ascii=False), s=score_auto,
                     t=datetime.now().isoformat(timespec="seconds"))
            # feedback immédiat sur les calculs
            st.success("Envoyé. C'est verrouillé.")
            for qu in act["questions"]:
                if qu["type"] == "texte":
                    continue
                d_ = detail[qu["id"]]
                if d_["ok"]:
                    st.write(f"✓ {qu['id']} : bonne réponse ({d_['pts']} pts)")
                else:
                    try:
                        att = eval(qu["solution"], {"__builtins__": {}}, dict(variables))
                        if qu["type"] == "choix":
                            att = qu["options"][int(float(att))]
                        st.write(f"✗ {qu['id']} : raté (bonne réponse : {att})")
                    except Exception:
                        st.write(f"✗ {qu['id']} : raté")
            st.write(f"**Score automatique : {score_auto:.1f} / 10** (les textes seront corrigés par ton prof)")
            if "debut" in st.session_state:
                del st.session_state["debut"]
            st.rerun()

st.sidebar.write(f"Connecté : {user}")
if st.sidebar.button("Quitter"):
    st.session_state.user = None
    st.rerun()
