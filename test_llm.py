import unittest
from unittest import mock

import llm
from core import PAUSE, render


class Status(unittest.TestCase):
    def test_full_name_adds_latest(self):
        self.assertEqual(llm.full_name("qwen3"), "qwen3:latest")
        self.assertEqual(llm.full_name("qwen3:8b"), "qwen3:8b")

    def test_model_missing(self):
        ok, text = llm.describe_status("0.12.0", ["gemma3:12b"], [], "qwen3:8b")
        self.assertFalse(ok)
        self.assertIn("ollama pull qwen3:8b", text)

    def test_ready_and_loaded(self):
        self.assertEqual(llm.describe_status("0.12.0", ["qwen3:latest"], [], "qwen3"),
                         (True, "Ollama 0.12.0 · qwen3 · bereit (wird bei Bedarf geladen)"))
        self.assertTrue(llm.describe_status("0.12.0", ["qwen3:8b"], ["qwen3:8b"], "qwen3:8b")[1].endswith("im Speicher"))

    def test_unreachable(self):
        with mock.patch.object(llm, "_get", side_effect=OSError("refused")):
            ok, text, models = llm.status("http://localhost:11434", "qwen3:8b")
        self.assertEqual((ok, models), (False, []))
        self.assertIn("nicht erreichbar", text)


class Smoothing(unittest.TestCase):
    def test_strips_pauses_and_quotes(self):
        with mock.patch.object(llm, "chat", return_value=' „Ich finde das gut.“ \n') as chat:
            self.assertEqual(llm.smooth(f"Ähm ich {PAUSE} finde das gut", "u", "m"), "Ich finde das gut.")
        self.assertNotIn(PAUSE, chat.call_args.args[3])

    def test_strips_think_block(self):
        with mock.patch.object(llm, "chat", return_value="<think>\nGrübel …\n</think>\nJa, gut."):
            self.assertEqual(llm.smooth("Äh ja gut", "u", "m"), "Ja, gut.")

    def test_empty_answer_raises(self):
        with mock.patch.object(llm, "chat", return_value="<think>x</think>  "), self.assertRaises(RuntimeError):
            llm.smooth("Ja gut", "u", "m")

    def test_suspicious(self):
        orig = "Äh, also ich finde, ähm, das Projekt eigentlich ganz gut, weil es uns hilft."
        self.assertFalse(llm.suspicious(orig, "Ich finde das Projekt eigentlich ganz gut, weil es uns hilft."))
        self.assertTrue(llm.suspicious(orig, "Gut."))  # stark gekürzt
        self.assertTrue(llm.suspicious(orig, orig + " Außerdem ist die Zusammenarbeit mit dem Team hervorragend."))

    def test_needs_smoothing_skips_filler_only_rows(self):
        ps = [{"text": "Ähm."}, {"text": "Gut so.", "smooth": "Gut so."}, {"text": "Ja klar."}]
        self.assertEqual(llm.needs_smoothing(ps), [2])


class RenderLlmForm(unittest.TestCase):
    def test_uses_smooth_column(self):
        ps = [{"start": 1, "end": 2, "speaker": "S", "text": "Äh ja gut", "smooth": "Ja, gut."},
              {"start": 3, "end": 4, "speaker": "S", "text": "Ähm."}]
        self.assertEqual(render("T", ps, {}, "geglaettet_llm")[1:], [("p", "00:00:01", "S", "Ja, gut.")])


class Summarize(unittest.TestCase):
    def test_summarize_reports_progress(self):
        ps = [{"start": 0, "end": 2, "speaker": "S", "text": "Wir testen die Zusammenfassung mit mehreren Wörtern."}]
        progress_calls = []

        def mock_chat(base_url, model, system, user, num_ctx, timeout=1800, on_chunk=None, cancelled=None):
            if on_chunk:
                on_chunk("## Thema A\n")
                on_chunk("- Erster Punkt der Zusammenfassung.\n")
                on_chunk("- Zweiter wichtiger Punkt.")
            return "## Thema A\n- Erster Punkt der Zusammenfassung.\n- Zweiter wichtiger Punkt."

        with mock.patch.object(llm, "chat", side_effect=mock_chat):
            res = llm.summarize(ps, {"S": "Person"}, "u", "m",
                                progress=lambda text, pct: progress_calls.append((text, pct)))

        self.assertIn("Thema A", res)
        self.assertTrue(len(progress_calls) >= 2)
        # First call is transcript ingestion (0%)
        self.assertEqual(progress_calls[0][1], 0)
        self.assertIn("Transkript wird eingelesen", progress_calls[0][0])
        # Last call is 100% completion
        self.assertEqual(progress_calls[-1][1], 100)
        self.assertIn("Zusammenfassung fertiggestellt", progress_calls[-1][0])


if __name__ == "__main__":
    unittest.main()
