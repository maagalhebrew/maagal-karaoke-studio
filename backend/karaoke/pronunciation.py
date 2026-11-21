"""English-readable pronunciation from the stress-marked Phonikud phoneme inventory."""
import re

SOUNDS = {"tʃ": "ch", "dʒ": "j", "ts": "ts", "ʔ": "", "χ": "ch", "ʃ": "sh", "ʁ": "r",
          "ʒ": "zh", "ɡ": "g", "j": "y", "a": "a", "e": "eh", "i": "ee", "o": "oh", "u": "oo"}
TOKEN = re.compile(r"tʃ|dʒ|ts|.", re.DOTALL)


def readable(word):
    tokens = TOKEN.findall(word)
    vowels = [i for i, t in enumerate(tokens) if t in "aeiou"]
    if not vowels:
        return word
    syllables = []
    start = 0
    for index, vowel in enumerate(vowels):
        if index + 1 == len(vowels):
            end = len(tokens)
        else:
            next_vowel = vowels[index + 1]
            onset = next_vowel - int(tokens[next_vowel - 1] == "ˈ")
            end = max(vowel + 1, onset - 1)
        value = "".join(SOUNDS.get(t, t) for t in tokens[start:end] if t != "ˈ")
        syllables.append(value.upper() if vowel and tokens[vowel - 1] == "ˈ" else value)
        start = end
    return "-".join(syllables)


def add_pronunciation(lines, model_path):
    from phonikud import phonemize
    from phonikud_onnx import Phonikud
    from phonikud_onnx.model import OnnxModel
    import onnxruntime
    from tokenizers import Tokenizer

    # The upstream constructor resolves a tokenizer by network repository ID.
    # Supply the identical pinned tokenizer from the installed model directory.
    class LocalModel(OnnxModel):
        def __init__(self):
            self.tokenizer = Tokenizer.from_file(str(model_path.parents[1] / "pronunciation-tokenizer/tokenizer.json"))
            self.max_context_length = 2046
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 4
            self.session = onnxruntime.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
            self.input_names = [item.name for item in self.session.get_inputs()]
            self.output_names = [item.name for item in self.session.get_outputs()]

    class LocalPhonikud(Phonikud):
        def __init__(self):
            self.model = LocalModel()

    model = LocalPhonikud()
    for line in lines:
        if not line.get("pronunciation"):
            text = " ".join(w["plain"] for w in line["words"])
            phonemes = phonemize(model.add_diacritics(text))
            line["pronunciation"] = " ".join(readable(w) for w in phonemes.split())
