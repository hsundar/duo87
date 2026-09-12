#!/usr/bin/env python3
"""Two-surface mockup: 5 button pages (A-E) + 3 wallpaper cards.

Exercises the real Deck against the hardware without any app config:

    python3 examples/mockup.py

* Horizontal swipe pages the tiles A->B->C->D->E (wraps); more than four pages
  is fine -- the four-slot limit is only on wallpaper cards.
* Swipe DOWN drops into the wallpaper carousel (stock -> card 1 -> 2 -> 3, the
  pad's own carousel); swipe UP returns to the tiles.
* Tapping a tile logs which page/key (fires on release, not on a swipe).

Run it as ONE process. Overlapping device opens (two scripts at once) or bursts
of LOG/MOD destabilise the pad; the real daemon holds the device singly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duo87
from deck.core import Deck, Page, WallpaperCard
from deck import render
from PIL import Image, ImageDraw

PAGE_COLOURS = {'A': (150, 40, 40), 'B': (40, 110, 60), 'C': (40, 70, 150),
                'D': (150, 110, 30), 'E': (90, 50, 140)}
CARD_COLOURS = [(150, 60, 20), (20, 110, 60), (40, 60, 160)]


class ButtonPage(Page):
    interval = None

    def __init__(self, letter):
        self.letter = letter
        self.title = 'page ' + letter

    def tiles(self, deck):
        out = {}
        for k in range(1, 13):
            im = Image.new('RGB', (render.SIZE, render.SIZE), PAGE_COLOURS[self.letter])
            d = ImageDraw.Draw(im)
            d.rectangle([1, 1, render.SIZE - 2, render.SIZE - 2], outline=(255, 255, 255), width=1)
            d.text((render.SIZE // 2, render.SIZE // 2 - 8), self.letter,
                   font=render.font(40, True), fill=(255, 255, 255), anchor='mm')
            d.text((render.SIZE // 2, render.SIZE - 16), 'k%d' % k,
                   font=render.font(14), fill=(230, 230, 230), anchor='mm')
            out[k] = im
        return out

    def on_press(self, deck, key):
        print('  TAP %s k%d' % (self.letter, key), flush=True)


class MockCard(WallpaperCard):
    interval = 3600

    def __init__(self, n):
        self.n = n
        self.title = 'card %d' % n

    def render(self, deck):
        im = Image.new('RGB', (duo87.PANEL_W, duo87.PANEL_H), CARD_COLOURS[self.n - 1])
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, duo87.PANEL_W - 1, duo87.PANEL_H - 1], outline=(255, 255, 255), width=10)
        d.text((duo87.PANEL_W // 2, duo87.PANEL_H // 2), 'CARD %d' % self.n,
               font=render.font(90, True), fill=(255, 255, 255), anchor='mm')
        return im


def main():
    pages = [ButtonPage(c) for c in 'ABCDE']
    cards = [MockCard(1), MockCard(2), MockCard(3)]
    log = lambda m: print('  %s' % m, flush=True)
    Deck(pages, cards=cards, log=log).run()


if __name__ == '__main__':
    main()
