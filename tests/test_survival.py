"""E6 — analyse de survie, validee sur des donnees synthetiques a reponse connue.

Ces tests sont ecrits **avant** les passes 2 et 3, donc avant d'avoir vu le moindre
chiffre reel. C'est leur raison d'etre : une analyse validee sur des donnees dont on
connait la reponse ne peut plus etre ajustee au resultat qu'on esperait.

Le procede est celui du jeu de controle E2, applique a la statistique : on fabrique un
monde dont on connait la demi-vie, on fait tourner l'estimateur dessus, et on verifie
qu'il retrouve le nombre.
"""

from __future__ import annotations

import math

import pytest

from artifact_rot.survival import (
    H1_GAP_THRESHOLD,
    H1_RATE_THRESHOLD,
    AgePoint,
    StratumCounts,
    pava,
    survival_curve,
    verdict_h1,
    wilson_difference,
    wilson_interval,
)


def exponential_world(half_life: float, ages: list[float], n: int = 4000) -> list[AgePoint]:
    """Un monde ou la survie suit une exponentielle de demi-vie connue.

    A l'age a, la proportion de liens encore vivants vaut 2**(-a / demi-vie). On observe
    chaque strate a son age, exactement comme le fait le projet : un instant unique,
    des articles d'ages differents.
    """
    points = []
    for age in ages:
        alive_fraction = 2 ** (-age / half_life)
        alive = round(n * alive_fraction)
        points.append(AgePoint(age_years=age, counts=StratumCounts(alive=alive, dead=n - alive)))
    return points


class TestWilson:
    def test_proportion_classique(self) -> None:
        low, high = wilson_interval(50, 100)
        assert low == pytest.approx(0.404, abs=0.01)
        assert high == pytest.approx(0.596, abs=0.01)

    def test_reste_dans_zero_un_aux_extremes(self) -> None:
        """L'interet de Wilson sur l'intervalle normal : pas de borne negative."""
        low, high = wilson_interval(0, 10)
        assert low == pytest.approx(0.0, abs=1e-12)
        assert 0 < high < 1
        low, high = wilson_interval(10, 10)
        assert high == pytest.approx(1.0, abs=1e-12)
        assert 0 < low < 1

    def test_effectif_nul(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_un_intervalle_se_resserre_avec_l_effectif(self) -> None:
        petit = wilson_interval(5, 10)
        grand = wilson_interval(500, 1000)
        assert (grand[1] - grand[0]) < (petit[1] - petit[0])


class TestDifferenceDeProportions:
    def test_difference_nette(self) -> None:
        low, high = wilson_difference(400, 1000, 100, 1000)
        assert low > 0
        assert 0.3 == pytest.approx((400 / 1000) - (100 / 1000), abs=1e-9)
        assert low < 0.3 < high

    def test_difference_nulle_contient_zero(self) -> None:
        low, high = wilson_difference(500, 1000, 500, 1000)
        assert low < 0 < high


class TestRegressionIsotone:
    def test_une_suite_deja_croissante_est_inchangee(self) -> None:
        values = [0.1, 0.2, 0.3, 0.4]
        assert pava(values, [1] * 4) == pytest.approx(values)

    def test_une_violation_est_regroupee(self) -> None:
        """Une survie qui remonte avec l'age est impossible : c'est du bruit, et
        l'afficher serait presenter un artefact comme un resultat."""
        out = pava([0.1, 0.5, 0.3, 0.6], [1] * 4)
        assert out == pytest.approx([0.1, 0.4, 0.4, 0.6])
        assert all(out[i] <= out[i + 1] + 1e-9 for i in range(len(out) - 1))

    def test_les_poids_comptent(self) -> None:
        """Une strate de 1 000 liens ne doit pas etre tiree par une strate de 10."""
        out = pava([0.5, 0.1], [1000, 10])
        assert out[0] == pytest.approx(out[1])
        assert out[0] > 0.45

    def test_suite_vide(self) -> None:
        assert pava([], []) == []


class TestDemiVie:
    @pytest.mark.parametrize("half_life", [3.0, 5.0, 8.0, 12.0])
    def test_retrouve_une_demi_vie_connue(self, half_life: float) -> None:
        """Le test central : un monde fabrique, une reponse connue d'avance."""
        ages = [1.0, 4.0, 8.0, 12.0, 16.0]
        curve = survival_curve(exponential_world(half_life, ages))
        estimated = curve.half_life
        assert estimated is not None, "la courbe devrait croiser 0,5"
        assert estimated == pytest.approx(half_life, rel=0.15)

    def test_aucune_demi_vie_si_la_courbe_ne_descend_pas(self) -> None:
        """Extrapoler au-dela de la derniere strate serait inventer le chiffre que tout
        le monde citera."""
        curve = survival_curve(exponential_world(50.0, [1.0, 4.0, 8.0]))
        assert curve.half_life is None

    def test_la_survie_decroit_toujours(self) -> None:
        curve = survival_curve(exponential_world(6.0, [1.0, 4.0, 8.0, 12.0, 16.0]))
        assert all(
            curve.survival[i] >= curve.survival[i + 1] - 1e-9
            for i in range(len(curve.survival) - 1)
        )

    def test_monde_sans_mortalite(self) -> None:
        points = [AgePoint(a, StratumCounts(alive=1000, dead=0)) for a in (1.0, 8.0, 16.0)]
        curve = survival_curve(points)
        assert curve.half_life is None
        assert curve.survival == pytest.approx([1.0, 1.0, 1.0])

    def test_coherence_avec_la_formule_exponentielle(self) -> None:
        """Verification independante : a une demi-vie, la survie theorique vaut 0,5."""
        assert 2 ** (-1.0) == pytest.approx(0.5)
        assert math.isclose(2 ** (-2.0), 0.25)


class TestDenominateurs:
    def test_unknown_n_entre_jamais_au_denominateur(self) -> None:
        """§4, piege 2. Un echec de crawl converti en taux est une falsification."""
        counts = StratumCounts(alive=40, dead=10, restricted=0, unknown=950)
        assert counts.denominator() == 50
        assert counts.dead_rate() == pytest.approx(0.2)
        assert counts.unknown_rate() == pytest.approx(0.95)

    def test_restricted_compte_vivant_par_defaut(self) -> None:
        counts = StratumCounts(alive=30, dead=10, restricted=10)
        assert counts.denominator("alive") == 50
        assert counts.dead_rate("alive") == pytest.approx(0.2)

    def test_variante_excluant_restricted(self) -> None:
        """Le choix est discutable : la variante est calculee et publiee a cote."""
        counts = StratumCounts(alive=30, dead=10, restricted=10)
        assert counts.denominator("exclude") == 40
        assert counts.dead_rate("exclude") == pytest.approx(0.25)

    def test_strate_vide(self) -> None:
        assert StratumCounts().dead_rate() is None


class TestVerdictH1:
    def test_h1_tenue(self) -> None:
        """Taux 2018 au-dessus de 20 % et ecart au-dessus de 15 points."""
        by_year = {
            2010: StratumCounts(alive=500, dead=500),
            2018: StratumCounts(alive=650, dead=350),
            2025: StratumCounts(alive=950, dead=50),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "tenue"
        assert result.reference_rate == pytest.approx(0.35)
        assert result.gap == pytest.approx(0.45)
        assert result.gap_interval is not None and result.gap_interval[0] > 0

    def test_h1_refutee_quand_les_liens_survivent(self) -> None:
        """Le plan impose de publier le resultat positif et de s'arreter."""
        by_year = {
            2010: StratumCounts(alive=980, dead=20),
            2018: StratumCounts(alive=985, dead=15),
            2025: StratumCounts(alive=990, dead=10),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "refutee"

    def test_h1_refutee_sans_effet_d_age(self) -> None:
        """Beaucoup de liens morts mais aucun rapport avec l'age.

        H1 affirme deux choses a la fois, dont que le taux croit **nettement** avec
        l'age. Sans effet d'age, elle est fausse quel que soit le taux — et le plan
        impose de publier et de s'arreter, pas d'elargir l'echantillon.
        """
        by_year = {
            2010: StratumCounts(alive=650, dead=350),
            2018: StratumCounts(alive=650, dead=350),
            2025: StratumCounts(alive=650, dead=350),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "refutee"
        assert any("age" in r for r in result.reasons)

    def test_zone_grise_effet_d_age_reel_mais_sous_le_seuil(self) -> None:
        """Le seul vrai cas de zone grise : les deux signaux existent, l'un des deux
        n'atteint pas son seuil. C'est la qu'elargir l'echantillon peut trancher."""
        by_year = {
            2010: StratumCounts(alive=670, dead=330),
            2018: StratumCounts(alive=750, dead=250),
            2025: StratumCounts(alive=770, dead=230),
        }
        result = verdict_h1(by_year)
        assert result.verdict == "zone_grise"
        assert result.gap is not None and 0 < result.gap < H1_GAP_THRESHOLD

    def test_petit_effectif_ne_suffit_pas(self) -> None:
        """Deux liens morts sur cinq font 40 %, mais l'intervalle est enorme. Le seuil
        seul ne suffit pas — c'est pour cela que le §2 exige un intervalle."""
        by_year = {
            2010: StratumCounts(alive=3, dead=2),
            2018: StratumCounts(alive=3, dead=2),
            2025: StratumCounts(alive=4, dead=1),
        }
        result = verdict_h1(by_year)
        assert result.verdict != "tenue"

    def test_strate_de_reference_absente(self) -> None:
        by_year = {2010: StratumCounts(alive=500, dead=500)}
        result = verdict_h1(by_year)
        assert result.verdict == "zone_grise"
        assert any("2018" in r for r in result.reasons)

    def test_le_taux_d_indetermination_est_reporte(self) -> None:
        by_year = {
            2010: StratumCounts(alive=500, dead=500, unknown=1000),
            2018: StratumCounts(alive=650, dead=350, unknown=0),
            2025: StratumCounts(alive=950, dead=50, unknown=0),
        }
        result = verdict_h1(by_year)
        assert result.unknown_rate == pytest.approx(1000 / 4000)

    def test_les_seuils_sont_ceux_du_plan(self) -> None:
        assert H1_RATE_THRESHOLD == 0.20
        assert H1_GAP_THRESHOLD == 0.15
