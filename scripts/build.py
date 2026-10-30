#!/usr/bin/env python3
"""Valide data/offres.json puis génère les fichiers dérivés.

Usage : python3 scripts/build.py            (valide + génère)
        python3 scripts/build.py --check    (valide seulement, code 1 si erreur)

Génère :
  data/offres.csv              une ligne par offre × puissance × poste (pour Excel / SQL)
  data/resume.json             meilleurs prix par option et puissance + coût annuel indicatif
  data/historique/AAAA-MM-JJ.json   copie du jour (pour suivre l'évolution des prix)
  CHANGELOG.md                 ce qui a changé depuis la copie précédente
  index.html                   page de consultation (données intégrées, aucune dépendance)
"""
import csv, json, sys, glob, os, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "offres.json")

POSTES = {
    "base": {"base"},
    "hphc": {"hp", "hc"},
    "tempo": {"bleu_hp", "bleu_hc", "blanc_hp", "blanc_hc", "rouge_hp", "rouge_hc"},
    "saisons": None,  # 4 ou 6 postes été/hiver
    "saisons_rouge": {"hiver_hp", "hiver_hc", "ete_hp", "ete_hc", "rouge_hp", "rouge_hc"},
    "week_end": {"semaine", "week_end"},
    "flex": {"eco_hp", "eco_hc", "sobriete_hp", "sobriete_hc"},
}
TYPES = {"reglemente", "indexe_trv", "fixe", "variable"}
VERIF = {"confirme", "source_unique", "conflit"}
# Profils pour le coût annuel indicatif (6 kVA par défaut)
PROFILS = {"base": None, "hphc": 0.32}  # part de la conso en heures creuses
CONSO_REF = [2500, 4500, 8000]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate(d):
    err, warn = [], []
    meta = d.get("meta", {})
    kvas = set(meta.get("puissances_kva", []))
    fids = {f["id"] for f in d.get("fournisseurs", [])}
    seen = set()
    for o in d.get("offres", []):
        oid = o.get("id", "?")
        p = f"[{oid}]"
        if oid in seen:
            err.append(f"{p} id en double")
        seen.add(oid)
        if o.get("fournisseur") not in fids:
            err.append(f"{p} fournisseur inconnu : {o.get('fournisseur')}")
        if o.get("option") not in POSTES:
            err.append(f"{p} option inconnue : {o.get('option')}")
        if o.get("type_prix") not in TYPES:
            err.append(f"{p} type_prix inconnu : {o.get('type_prix')}")
        if o.get("verification") not in VERIF:
            err.append(f"{p} verification inconnue : {o.get('verification')}")
        vm = o.get("verification_manuelle")
        if vm is not None:
            try:
                datetime.date.fromisoformat(vm.get("le", ""))
            except Exception:
                err.append(f"{p} verification_manuelle.le doit être une date AAAA-MM-JJ")
            if not vm.get("par"):
                err.append(f"{p} verification_manuelle.par manquant")
        if not o.get("sources"):
            err.append(f"{p} aucune source")
        if not o.get("grille"):
            err.append(f"{p} grille vide")
        prev_abo = 0
        for r in o.get("grille", []):
            k = r.get("kva")
            if k not in kvas:
                err.append(f"{p} puissance inattendue {k}")
            a = r.get("abonnement_mois")
            if a is not None:
                if not 5 <= a <= 150:
                    err.append(f"{p} {k} kVA abonnement hors bornes : {a}")
                if a < prev_abo:
                    warn.append(f"{p} abonnement qui baisse quand la puissance monte ({k} kVA)")
                prev_abo = a
            pk = r.get("prix_kwh") or {}
            exp = POSTES.get(o.get("option"))
            if exp is not None and set(pk) != exp:
                err.append(f"{p} {k} kVA postes {sorted(pk)} ≠ attendus {sorted(exp)}")
            for poste, v in pk.items():
                if not isinstance(v, (int, float)) or not 0.04 <= v <= 1.2:
                    err.append(f"{p} {k} kVA prix {poste} hors bornes : {v}")
        for pr in o.get("promotions", []):
            fin = pr.get("date_fin")
            if fin and fin < meta.get("mis_a_jour_le", ""):
                warn.append(f"{p} promotion expirée ({fin}) : à retirer")
        try:
            age = (datetime.date.fromisoformat(meta["mis_a_jour_le"]) -
                   datetime.date.fromisoformat(o["derniere_verif"])).days
            if age > 14:
                warn.append(f"{p} non revérifiée depuis {age} jours")
        except Exception:
            err.append(f"{p} date derniere_verif invalide")
    warn += check_ttc(d)
    return err, warn


def check_ttc(d):
    """Repère les prix probablement saisis HT au lieu de TTC.
    kWh : HT implicite = TTC / (1 + TVA) - accise ; un prix HT saisi par erreur donne un HT implicite anormalement bas.
    Abonnement : comparé à l'abonnement TTC du Tarif Bleu à la même puissance ; un HT est environ 20 à 30 % plus bas."""
    f = d["meta"].get("fiscalite", {})
    tva, acc = f.get("tva", 0.20), f.get("accise_kwh_ht", 0.0306)
    ref = next((o for o in d["offres"] if o["id"] == "edf-tarif-bleu-hphc"), None)
    tabo = {g["kva"]: g["abonnement_mois"] for g in ref["grille"]} if ref else {}
    out = []
    for o in d["offres"]:
        for g in o["grille"]:
            for k, v in g["prix_kwh"].items():
                if v / (1 + tva) - acc < 0.045:
                    out.append(f"[{o['id']}] {g['kva']} kVA {k} = {v} € : prix très bas, vérifier qu'il est bien TTC")
            a, t = g.get("abonnement_mois"), tabo.get(g["kva"])
            if a and t and a / t < 0.85:
                out.append(f"[{o['id']}] {g['kva']} kVA abonnement {a} € < 85 % du Tarif Bleu ({t} €) : vérifier qu'il est bien TTC")
    return out


_DREF = [None]


def d_ref():
    return _DREF[0] or ""


def annual(o, kva, conso):
    r = next((g for g in o["grille"] if g["kva"] == kva), None)
    if not r or r.get("abonnement_mois") is None or o["option"] not in PROFILS:
        return None
    pk = r["prix_kwh"]
    if o["option"] == "base":
        energie = conso * pk["base"]
    else:
        hc = PROFILS["hphc"]
        energie = conso * ((1 - hc) * pk["hp"] + hc * pk["hc"])
    promo = sum((p.get("valeur_an1_eur") or 0) + (p.get("mois_abonnement_offerts") or 0) * r["abonnement_mois"]
                for p in o.get("promotions", []) if not p.get("date_fin") or p["date_fin"] >= d_ref())
    an = 12 * r["abonnement_mois"] + energie
    return round(an, 2), round(an - promo, 2), round(3 * an - promo, 2), promo


def resume(d):
    names = {f["id"]: f["nom"] for f in d["fournisseurs"]}
    out = {"mis_a_jour_le": d["meta"]["mis_a_jour_le"],
           "hypotheses": {"part_heures_creuses_hphc": PROFILS["hphc"], "consommations_kwh": CONSO_REF,
                          "note": "Estimation indicative pour les options Base et HP/HC ; Tempo et offres à saisons dépendent du profil horaire (utiliser le prompt)."},
           "classements": {}}
    for kva in d["meta"]["puissances_kva"]:
        for conso in CONSO_REF:
            rows = []
            for o in d["offres"]:
                a = annual(o, kva, conso)
                if a:
                    rows.append({"id": o["id"], "fournisseur": names[o["fournisseur"]], "offre": o["offre"],
                                 "option": o["option"], "cout_annuel": a[0], "cout_annuel_promo_deduite": a[1],
                                 "cout_3_ans_promo_deduite": a[2], "promo_an1": a[3],
                                 "verification": o["verification"]})
            rows.sort(key=lambda x: x["cout_annuel_promo_deduite"])
            out["classements"][f"{kva}kVA_{conso}kWh"] = rows
    return out


def csv_rows(d):
    names = {f["id"]: f["nom"] for f in d["fournisseurs"]}
    for o in d["offres"]:
        for r in o["grille"]:
            for poste, v in r["prix_kwh"].items():
                yield [o["id"], names[o["fournisseur"]], o["offre"], o["option"], o["type_prix"], r["kva"],
                       r.get("abonnement_mois"), poste, v, o["verification"], o["derniere_verif"]]


def diff(old, new):
    def flat(d):
        m = {}
        for o in d["offres"]:
            for r in o["grille"]:
                m[(o["id"], r["kva"], "abonnement")] = r.get("abonnement_mois")
                for k, v in r["prix_kwh"].items():
                    m[(o["id"], r["kva"], k)] = v
        return m
    a, b = flat(old), flat(new)
    lines = []
    ids_old = {o["id"] for o in old["offres"]}
    ids_new = {o["id"] for o in new["offres"]}
    for i in sorted(ids_new - ids_old):
        lines.append(f"- Nouvelle offre : `{i}`")
    for i in sorted(ids_old - ids_new):
        lines.append(f"- Offre retirée : `{i}`")
    for key in sorted(set(a) & set(b), key=str):
        if a[key] != b[key] and key[1] == 6:  # résumé à 6 kVA pour rester lisible
            lines.append(f"- `{key[0]}` {key[2]} (6 kVA) : {a[key]} → {b[key]}")
    po = {o["id"]: [p["description"] for p in o.get("promotions", [])] for o in old["offres"]}
    for o in new["offres"]:
        np_ = [p["description"] for p in o.get("promotions", [])]
        if o["id"] in po and po[o["id"]] != np_:
            lines.append(f"- `{o['id']}` promotions : {po[o['id']] or 'aucune'} → {np_ or 'aucune'}")
    return lines


def main():
    d = load(DATA)
    _DREF[0] = d["meta"]["mis_a_jour_le"]
    err, warn = validate(d)
    for w in warn:
        print("AVERTISSEMENT", w)
    for e in err:
        print("ERREUR", e)
    if err:
        sys.exit(1)
    if "--check" in sys.argv:
        print(f"OK : {len(d['offres'])} offres valides")
        return

    with open(os.path.join(ROOT, "data", "offres.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "fournisseur", "offre", "option", "type_prix", "kva", "abonnement_mois_ttc",
                    "poste", "prix_kwh_ttc", "verification", "derniere_verif"])
        w.writerows(csv_rows(d))

    res = resume(d)
    with open(os.path.join(ROOT, "data", "resume.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    hist_dir = os.path.join(ROOT, "data", "historique")
    os.makedirs(hist_dir, exist_ok=True)
    day = d["meta"]["mis_a_jour_le"]
    prev = sorted(p for p in glob.glob(os.path.join(hist_dir, "*.json")) if os.path.basename(p) < f"{day}.json")
    with open(os.path.join(hist_dir, f"{day}.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))

    cl = os.path.join(ROOT, "CHANGELOG.md")
    body = open(cl, encoding="utf-8").read() if os.path.exists(cl) else "# Évolution des prix\n"
    header, _, rest = body.partition("\n")
    marker = f"\n## {day}\n"
    if prev:
        lines = diff(load(prev[-1]), d) or ["- Aucun changement de prix."]
    else:
        lines = [f"- Première version : {len(d['offres'])} offres, {len(d['fournisseurs'])} fournisseurs."]
    section = marker + "\n".join(lines) + "\n"
    if marker in rest:  # remplace la section du jour si on relance
        before, _, after = rest.partition(marker)
        after = after[after.find("\n## ") + 1:] if "\n## " in after else ""
        rest = before + section + after
    else:
        rest = section + rest
    with open(cl, "w", encoding="utf-8") as f:
        f.write(header + "\n" + rest)

    tpl = open(os.path.join(ROOT, "site", "template.html"), encoding="utf-8").read()
    payload = json.dumps({"data": d, "resume": res}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = tpl.replace("/*__DATA__*/null", payload)
    head = ('<!doctype html>\n<html lang="fr">\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<style>body{margin:0}[hidden]{display:none!important}</style>\n')
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(head + page)
    print(f"OK : {len(d['offres'])} offres, {len(warn)} avertissement(s)")


if __name__ == "__main__":
    main()
