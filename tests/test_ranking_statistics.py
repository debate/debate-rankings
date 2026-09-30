import json
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main as rankings_main
from main import RankingSystem


class RankingStatisticsTest(unittest.TestCase):
    def test_exports_individual_and_field_wide_win_rates(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tournament = root / "tournaments" / "test-format" / "invitational"
            tournament.mkdir(parents=True)
            (root / "output").mkdir()

            (root / "config.json").write_text(
                json.dumps(
                    {
                        "tournaments": ["invitational"],
                        "majors": ["invitational"],
                        "multi_team_debaters": [],
                    }
                )
            )
            pd.DataFrame(
                [
                    {"Institution": "Alpha", "Entry": "Alice", "Code": "Alpha A"},
                    {"Institution": "Beta", "Entry": "Bob", "Code": "Beta B"},
                    {"Institution": "Gamma", "Entry": "Charlie", "Code": "Gamma C"},
                ]
            ).to_csv(tournament / "entries.csv", index=False)

            pd.DataFrame(
                [{"Aff": "Alpha A", "Neg": "Beta B", "Judge": "J1", "Win": "Aff"}]
            ).to_csv(tournament / "01-round-1.csv", index=False)
            pd.DataFrame(
                [{"Aff": "Beta B", "Neg": "Alpha A", "Judge": "J2", "Win": "Aff"}]
            ).to_csv(tournament / "02-round-2.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "Aff": "Alpha A",
                        "Neg": "Beta B",
                        "Judges": "J1 J2 J3",
                        "Votes": "Neg Neg Aff",
                        "Win": "Neg",
                    }
                ]
            ).to_csv(tournament / "123456.csv", index=False)
            pd.DataFrame(
                [{"Aff": "Beta B", "Neg": "Alpha A", "Judge": "J3", "Win": "Neg"}]
            ).to_csv(tournament / "04-finals.csv", index=False)

            previous_directory = Path.cwd()
            try:
                os.chdir(root)
                RankingSystem("config.json", "test-format").run("test_")
            finally:
                os.chdir(previous_directory)

            rankings = pd.read_csv(root / "output" / "test_rankings.csv").set_index("Name")
            full_rankings = pd.read_csv(
                root / "output" / "test_full_rankings.csv"
            ).set_index("Name")
            field_statistics_path = root / "output" / "test_field_statistics.csv"
            self.assertTrue(field_statistics_path.exists())
            field_statistics = pd.read_csv(
                field_statistics_path
            )

            expected_columns = [
                "Aff Win Rate",
                "Neg Win Rate",
                "Aff Elim Win Rate",
                "Neg Elim Win Rate",
            ]
            self.assertEqual(len(field_statistics), 1)
            self.assertEqual(
                field_statistics.loc[0, expected_columns].to_dict(),
                {
                    "Aff Win Rate": 50.0,
                    "Neg Win Rate": 50.0,
                    "Aff Elim Win Rate": 0.0,
                    "Neg Elim Win Rate": 100.0,
                },
            )
            for output in (rankings, full_rankings):
                self.assertTrue(set(expected_columns).issubset(output.columns))
                self.assertEqual(output.loc["Alice", "Aff Win Rate"], 50.0)
                self.assertEqual(output.loc["Alice", "Neg Win Rate"], 50.0)
                self.assertEqual(output.loc["Alice", "Aff Elim Win Rate"], 0.0)
                self.assertEqual(output.loc["Alice", "Neg Elim Win Rate"], 100.0)
                self.assertEqual(output.loc["Bob", "Aff Win Rate"], 50.0)
                self.assertEqual(output.loc["Bob", "Neg Win Rate"], 50.0)
                self.assertEqual(output.loc["Bob", "Aff Elim Win Rate"], 0.0)
                self.assertTrue(pd.isna(output.loc["Charlie", "Aff Win Rate"]))
                self.assertTrue(pd.isna(output.loc["Charlie", "Neg Win Rate"]))
                self.assertTrue(pd.isna(output.loc["Charlie", "Aff Elim Win Rate"]))
                self.assertTrue(pd.isna(output.loc["Charlie", "Neg Elim Win Rate"]))
                self.assertEqual(output.loc["Bob", "Neg Elim Win Rate"], 100.0)

    def test_parses_kentucky_rr_entries_and_results(self):
        repository_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tournament_root = root / "tournaments" / "cpd"
            tournament_root.mkdir(parents=True)
            shutil.copytree(
                repository_root / "tournaments" / "cpd" / "kentucky-rr",
                tournament_root / "kentucky-rr",
                dirs_exist_ok=True,
            )
            (root / "output").mkdir()
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "tournaments": ["kentucky-rr"],
                        "majors": [],
                        "multi_team_debaters": [],
                    }
                )
            )

            previous_directory = Path.cwd()
            try:
                os.chdir(root)
                ranking_system = RankingSystem("config.json", "cpd")
                ranking_system.update_from_tournament("kentucky-rr")
            finally:
                os.chdir(previous_directory)

            self.assertEqual(len(ranking_system.debaters), 7)
            self.assertEqual(
                sorted(ranking_system.debaters["Code"].tolist()),
                [
                    "CSU Long Beach",
                    "Dartmouth",
                    "Emory",
                    "Kansas",
                    "Kentucky",
                    "Michigan",
                    "Michigan State",
                ],
            )
            self.assertEqual(
                sum(
                    statistics["aff_rounds"] + statistics["neg_rounds"]
                    for statistics in ranking_system.win_statistics.values()
                ),
                42,
            )

            kentucky_hash = ranking_system.debaters.set_index("Code").loc[
                "Kentucky", "hash"
            ]
            self.assertEqual(
                ranking_system.win_statistics[kentucky_hash],
                {
                    "aff_wins": 0,
                    "aff_rounds": 3,
                    "neg_wins": 0,
                    "neg_rounds": 3,
                    "aff_elim_wins": 0,
                    "aff_elim_rounds": 0,
                    "neg_elim_wins": 0,
                    "neg_elim_rounds": 0,
                },
            )


class TopicTournamentPartitionTest(unittest.TestCase):
    def test_keeps_tournaments_in_current_topic_until_boundary_exists(self):
        tournaments = ["loyola-rr", "loyola", "ukso", "grapevine"]

        partitions = rankings_main.partition_tournaments_by_topic(
            tournaments,
            {"sepoct_end": "meadows", "novdec_end": "isidore"},
        )

        self.assertEqual(partitions, (tournaments, [], []))

    def test_partitions_topics_through_inclusive_boundaries(self):
        tournaments = [
            "early",
            "sepoct-last",
            "middle",
            "novdec-last",
            "late",
        ]

        partitions = rankings_main.partition_tournaments_by_topic(
            tournaments,
            {"sepoct_end": "sepoct-last", "novdec_end": "novdec-last"},
        )

        self.assertEqual(
            partitions,
            (
                ["early", "sepoct-last"],
                ["middle", "novdec-last"],
                ["late"],
            ),
        )


if __name__ == "__main__":
    unittest.main()
