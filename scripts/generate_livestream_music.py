"""生成原创16秒营业配乐；无外部采样，可重复生成完全相同的 PCM 文件。"""
import array
import math
from pathlib import Path
import sys
import wave


THEMES = {
    '小肥鱼营业曲': (.5, 0, [72, 76, 79, 76, 74, 77, 81, 77, 76, 79, 83, 79, 74, 77, 79, 71], .2),
    '心动小曲': (.55, 0, [76, 79, 84, 83, 79, 76, 74, 76, 77, 81, 84, 81, 79, 76, 74, 72], .1),
    '花开小曲': (.65, 0, [72, 76, 79, 84, 83, 79, 77, 76, 74, 77, 81, 84, 79, 76, 74, 72], .04),
    '糖果小曲': (.36, 12, [72, 79, 76, 79, 74, 81, 77, 81, 76, 83, 79, 83, 77, 79, 76, 72], .3),
    '庆典小曲': (.3, 0, [72, 72, 79, 79, 81, 79, 76, 72, 77, 77, 81, 81, 79, 83, 84, 84], .5),
    '摇摆舞曲': (.4, 0, [72, 76, 79, 81, 79, 76, 74, 72, 74, 77, 81, 83, 81, 79, 76, 72], .35),
    '棋盘小曲': (.75, -12, [72, 79, 76, 74, 77, 81, 79, 76, 74, 77, 81, 79, 76, 74, 71, 72], .02),
    '像素闯关': (.25, 0, [72, 79, 84, 79, 74, 81, 86, 81, 76, 83, 88, 83, 77, 84, 79, 84], .65),
}


def generate(path, theme=None):
    rate = 22050
    beat, transpose, phrase, harmonic = theme or THEMES['小肥鱼营业曲']
    # C 大调原创短句，四小节 x 两遍；低音根音和弱拍小铃铛。
    notes = [note + transpose for note in phrase] * 2
    roots = [48, 53, 55, 55, 48, 53, 55, 48]
    pcm = array.array('h')
    for i in range(int(len(notes) * beat * rate)):
        t = i / rate
        step = min(len(notes) - 1, int(t / beat))
        phase = t % beat
        f = 440 * 2 ** ((notes[step] - 69) / 12)
        env = min(1, phase / .015) * math.exp(-phase * 7)
        melody = env * (math.sin(2 * math.pi * f * t) + harmonic * math.sin(4 * math.pi * f * t))
        bass_f = 440 * 2 ** ((roots[step // 4] - 69) / 12)
        bass = .36 * math.sin(2 * math.pi * bass_f * t) * math.exp(-phase * 4)
        kick = .22 * math.sin(2 * math.pi * (55 * phase + 4 * (1 - math.exp(-phase * 20)))) * math.exp(-phase * 22)
        fade = min(1, t / .03, (len(notes) * beat - t) / .2)
        pcm.append(round(12000 * (melody + bass + kick) * fade))
    if sys.byteorder != 'little':
        pcm.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm.tobytes())


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1] / 'assets/sounds/livestream'
    for name, theme in THEMES.items():
        generate(root / f'{name}.wav', theme)
