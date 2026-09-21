"""E6 — courbe de survie, demi-vie, et verdict sur H1.

**Ecrit le 2026-09-21, avant les passes 2 et 3, et donc avant d'avoir vu le moindre
chiffre final.** C'est deliberé : une analyse ecrite apres coup peut toujours etre
ajustee, meme de bonne foi, jusqu'a ce qu'elle dise ce qu'on esperait. Ecrite avant, elle
ne le peut plus. Le §2 du plan exige deja que le critere de decision soit fixe avant le
premier run ; ce module en est la traduction executable.

---

## Un ecart au PLAN.md §6, et c'est le point important de ce fichier

Le plan prescrit **Kaplan-Meier**. Kaplan-Meier ne s'applique pas a ces donnees, et
l'utiliser produirait une courbe d'apparence impeccable et fausse.

Kaplan-Meier suppose qu'on observe, pour chaque sujet, **soit sa date de mort, soit la
date ou on l'a vu vivant pour la derniere fois**. Ici, on n'observe jamais la date de
mort d'un lien. On regarde, a un instant unique, des liens issus d'articles d'ages
differents, et on note pour chacun : vivant ou mort **aujourd'hui**.

Autrement dit, pour un lien d'un article de huit ans, on sait seulement :
  * s'il est mort  -> il est mort quelque part entre 0 et 8 ans. Rien de plus.
  * s'il est vivant -> il a survecu au moins 8 ans.

C'est ce que la litterature appelle des **donnees de statut courant** (interception a un
instant, ou censure par intervalle de cas 1). L'estimateur non parametrique adapte n'est
pas Kaplan-Meier mais la **regression isotone** de la proportion de morts en fonction de
l'age — equivalente ici a l'estimateur de Turnbull, et obtenue par l'algorithme de
regroupement des violations adjacentes (PAVA).

Donner ces donnees a Kaplan-Meier reviendrait a lui affirmer que chaque lien mort est
mort le jour de la publication de son article. La courbe obtenue serait systematiquement
trop pessimiste, et rien dans sa forme ne le signalerait.

**Ce que la regression isotone apporte en plus** : elle impose que la survie decroisse
avec l'age. Si le bruit d'echantillonnage fait remonter une strate — 2014 mieux servie
que 2018, par exemple — elle regroupe les deux plutot que de publier une courbe qui
remonte, ce qui serait un artefact et non un resultat.

Quand le projet aura deux campagnes espacees de six mois, les donnees deviendront
reellement censurees par intervalle avec des bornes connues, et Turnbull s'appliquera
sous sa forme generale. Kaplan-Meier ne s'appliquera toujours pas.

---

## Ce qui n'entre jamais dans un denominateur

`unknown` (§4, piege 2). Jamais, sous aucun pretexte. Il est compte et reporte a part.

`restricted` est plus delicat : la ressource existe, elle ne resout simplement pas en
acces libre. Le calcul principal la compte **vivante** — c'est ce qu'elle est, au sens
de l'existence. Une variante qui l'exclut entierement du denominateur est calculee en
meme temps et publiee a cote, parce que le choix est discutable et qu'un lecteur doit
pouvoir voir ce qu'il change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

Z95 = 1.959963984540054

RestrictedPolicy = Literal["alive", "exclude"]


# --- Intervalle de confiance -----------------------------------------------------------


def wilson_interval(successes: int, total: int, z: float = Z95) -> tuple[float, float]:
    """Intervalle de Wilson pour une proportion. Exige par le §2 du plan.

    Prefere a l'intervalle normal parce qu'il reste valide sur de petits effectifs et
    pres de 0 ou de 1 — exactement la situation des strates les moins peuplees, ou
    l'intervalle normal produit des bornes negatives ou superieures a un.
    """
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def wilson_difference(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float]:
    """Intervalle de la **difference** de deux proportions, methode de Newcombe.

    Le §2 demande que l'ecart entre la strate la plus ancienne et la plus recente
    depasse quinze points avec un intervalle excluant zero. C'est un intervalle sur une
    difference qu'il faut, pas deux intervalles separes : deux intervalles qui se
    chevauchent legerement peuvent tres bien correspondre a une difference
    significative, et l'erreur inverse est encore plus frequente.
    """
    if n1 <= 0 or n2 <= 0:
        return (-1.0, 1.0)
    l1, u1 = wilson_interval(k1, n1, z)
    l2, u2 = wilson_interval(k2, n2, z)
    p1, p2 = k1 / n1, k2 / n2
    lower = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


# --- Strates ---------------------------------------------------------------------------


@dataclass
class StratumCounts:
    """Comptes bruts d'une strate. Les quatre etats y sont, y compris ceux qu'on exclut."""

    alive: int = 0
    dead: int = 0
    restricted: int = 0
    unknown: int = 0

    @property
    def total_observed(self) -> int:
        """Tout ce qui a ete observe, `unknown` compris. Sert a calculer le taux
        d'indetermination, jamais un taux de mortalite."""
        return self.alive + self.dead + self.restricted + self.unknown

    def denominator(self, policy: RestrictedPolicy = "alive") -> int:
        """Denominateur d'un taux publie. `unknown` n'y figure jamais (§4, piege 2)."""
        base = self.alive + self.dead
        return base + self.restricted if policy == "alive" else base

    def numerator(self) -> int:
        return self.dead

    def dead_rate(self, policy: RestrictedPolicy = "alive") -> float | None:
        n = self.denominator(policy)
        return self.dead / n if n else None

    def unknown_rate(self) -> float | None:
        n = self.total_observed
        return self.unknown / n if n else None


@dataclass
class AgePoint:
    """Une strate d'age : proportion de morts observee a cet age."""

    age_years: float
    counts: StratumCounts
    label: str = ""

    def rate(self, policy: RestrictedPolicy = "alive") -> float:
        return self.counts.dead_rate(policy) or 0.0

    def interval(self, policy: RestrictedPolicy = "alive") -> tuple[float, float]:
        return wilson_interval(self.counts.dead, self.counts.denominator(policy))


# --- Courbe de survie ------------------------------------------------------------------


def pava(values: list[float], weights: list[float]) -> list[float]:
    """Regression isotone croissante, par regroupement des violations adjacentes.

    Rend la suite croissante la plus proche des valeurs observees, au sens des moindres
    carres ponderes. Appliquee ici a la proportion de morts en fonction de l'age : une
    proportion de morts ne peut pas diminuer quand l'age augmente, et si l'echantillon
    dit le contraire, c'est du bruit.

    Regrouper deux strates plutot que publier une courbe qui remonte n'est pas un
    lissage cosmetique : une survie qui augmente avec l'age est impossible, et l'afficher
    serait presenter un artefact d'echantillonnage comme un resultat.
    """
    if not values:
        return []
    blocks: list[tuple[float, float]] = []  # (moyenne, poids)
    for value, weight in zip(values, weights, strict=True):
        blocks.append((value, max(weight, 1e-12)))
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            (v2, w2), (v1, w1) = blocks.pop(), blocks.pop()
            blocks.append(((v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2))

    out: list[float] = []
    index = 0
    for mean, weight in blocks:
        size = 0
        acc = 0.0
        while index + size < len(values) and acc < weight - 1e-9:
            acc += max(weights[index + size], 1e-12)
            size += 1
        out.extend([mean] * size)
        index += size
    return out[: len(values)]


@dataclass
class SurvivalCurve:
    ages: list[float]
    survival: list[float]
    raw_dead_rate: list[float]
    intervals: list[tuple[float, float]]
    labels: list[str] = field(default_factory=list)
    policy: RestrictedPolicy = "alive"

    @property
    def half_life(self) -> float | None:
        """Age auquel la survie atteint 0,5, par interpolation lineaire.

        Rend `None` si la courbe ne descend jamais sous 0,5 sur la plage observee.
        **Extrapoler au-dela de la strate la plus ancienne serait inventer un chiffre** :
        on ne dispose d'aucune observation au-dela, et c'est precisement le chiffre que
        tout le monde citera. S'il n'est pas atteint, le rapport doit le dire — « la
        demi-vie depasse N ans » est une information ; un nombre extrapole n'en est pas
        une.
        """
        for i in range(len(self.survival)):
            if self.survival[i] <= 0.5:
                if i == 0:
                    return self.ages[0]
                s0, s1 = self.survival[i - 1], self.survival[i]
                a0, a1 = self.ages[i - 1], self.ages[i]
                if s0 == s1:
                    return a1
                return a0 + (s0 - 0.5) * (a1 - a0) / (s0 - s1)
        return None


def survival_curve(points: list[AgePoint], policy: RestrictedPolicy = "alive") -> SurvivalCurve:
    ordered = sorted(points, key=lambda p: p.age_years)
    ages = [p.age_years for p in ordered]
    raw = [p.rate(policy) for p in ordered]
    weights = [float(p.counts.denominator(policy)) for p in ordered]
    monotone = pava(raw, weights)
    return SurvivalCurve(
        ages=ages,
        survival=[1.0 - d for d in monotone],
        raw_dead_rate=raw,
        intervals=[p.interval(policy) for p in ordered],
        labels=[p.label for p in ordered],
        policy=policy,
    )


# --- Verdict sur H1 ---------------------------------------------------------------------

H1_RATE_THRESHOLD = 0.20
H1_GAP_THRESHOLD = 0.15
H1_REFERENCE_YEAR = 2018
GREY_ZONE_FACTOR = 3

Verdict = Literal["tenue", "refutee", "zone_grise"]


@dataclass
class H1Result:
    verdict: Verdict
    reference_rate: float | None
    reference_interval: tuple[float, float] | None
    gap: float | None
    gap_interval: tuple[float, float] | None
    unknown_rate: float
    reasons: list[str]
    policy: RestrictedPolicy


def verdict_h1(
    by_year: dict[int, StratumCounts],
    policy: RestrictedPolicy = "alive",
) -> H1Result:
    """Le critere du §2, applique tel qu'il est ecrit. Aucune marge d'interpretation.

    « H1 tenue si le taux de liens non resolus depasse 20 % sur la strate 2018, **et**
    si l'ecart entre la strate la plus ancienne et la plus recente depasse 15 points,
    IC 95 % (Wilson) excluant 0 sur les deux. »

    La fonction ne prend aucune decision qui ne soit pas dans cette phrase. C'est tout
    l'interet de l'avoir ecrite avant d'avoir les chiffres.
    """
    reasons: list[str] = []
    years = sorted(by_year)
    if not years:
        return H1Result("zone_grise", None, None, None, None, 0.0, ["aucune strate"], policy)

    oldest, newest = by_year[years[0]], by_year[years[-1]]
    ref = by_year.get(H1_REFERENCE_YEAR)

    total_obs = sum(c.total_observed for c in by_year.values())
    total_unknown = sum(c.unknown for c in by_year.values())
    unknown_rate = total_unknown / total_obs if total_obs else 0.0

    if ref is None:
        reasons.append(f"strate de reference {H1_REFERENCE_YEAR} absente")
        return H1Result("zone_grise", None, None, None, None, unknown_rate, reasons, policy)

    ref_rate = ref.dead_rate(policy)
    ref_ci = wilson_interval(ref.dead, ref.denominator(policy))

    gap = None
    gap_ci = None
    old_rate, new_rate = oldest.dead_rate(policy), newest.dead_rate(policy)
    if old_rate is not None and new_rate is not None:
        gap = old_rate - new_rate
        gap_ci = wilson_difference(
            oldest.dead, oldest.denominator(policy), newest.dead, newest.denominator(policy)
        )

    rate_ok = ref_rate is not None and ref_rate > H1_RATE_THRESHOLD and ref_ci[0] > 0
    gap_ok = gap is not None and gap > H1_GAP_THRESHOLD and gap_ci is not None and gap_ci[0] > 0

    if rate_ok:
        reasons.append(
            f"taux {H1_REFERENCE_YEAR} = {ref_rate:.1%} > {H1_RATE_THRESHOLD:.0%}, "
            f"IC [{ref_ci[0]:.1%} ; {ref_ci[1]:.1%}]"
        )
    else:
        reasons.append(
            f"taux {H1_REFERENCE_YEAR} = "
            f"{ref_rate:.1%}" if ref_rate is not None else "taux indisponible"
        )
    if gap_ok:
        reasons.append(
            f"ecart {years[0]}-{years[-1]} = {gap:.1%} > {H1_GAP_THRESHOLD:.0%}, "
            f"IC [{gap_ci[0]:.1%} ; {gap_ci[1]:.1%}]"
        )
    elif gap is not None:
        reasons.append(f"ecart {years[0]}-{years[-1]} = {gap:.1%}")

    # « H1 refutee si le taux reste sous 20 % **partout** OU si l'effet d'age est nul. »
    #
    # Le plan ecrit « ou », et la premiere version de ce code avait lu « et ». La
    # difference n'est pas cosmetique : avec « et », un monde ou les liens meurent
    # beaucoup mais sans aucun rapport avec l'age serait classe « zone grise » et
    # justifierait d'elargir l'echantillon. Or H1 affirme deux choses a la fois, dont
    # que « le taux de mort croit nettement avec l'age ». Sans effet d'age, H1 est
    # fausse, quel que soit le taux — et le plan impose alors de publier et de s'arreter.
    rates = [c.dead_rate(policy) for c in by_year.values()]
    all_below = all(r is not None and r < H1_RATE_THRESHOLD for r in rates)
    no_age_effect = gap_ci is not None and gap_ci[0] <= 0 <= gap_ci[1]

    if rate_ok and gap_ok:
        verdict: Verdict = "tenue"
    elif all_below:
        verdict = "refutee"
        reasons.append(f"toutes les strates sous {H1_RATE_THRESHOLD:.0%}")
    elif no_age_effect:
        verdict = "refutee"
        reasons.append("effet d'age non demontre : l'intervalle de l'ecart contient zero")
    else:
        verdict = "zone_grise"
        reasons.append(
            f"un critere sur deux : elargir l'echantillon une seule fois, "
            f"facteur {GREY_ZONE_FACTOR} (§2)"
        )

    return H1Result(verdict, ref_rate, ref_ci, gap, gap_ci, unknown_rate, reasons, policy)
