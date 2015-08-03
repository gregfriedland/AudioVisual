# Demo program for wrapping a Vamp plugin to visualize sound data.
# Uses the 'qm-transcription' Vamp plugin to turn an audio file into
# a sequence of notes (time of occurence, duration and midi key).
# This is visualized as a keyboard with each midi note represented by
# one key.

# Usage keyboard_demo.py <sound-file>

import subprocess as sp
import numpy
import sys
import vamp
import pygame as pg
from pygame.locals import FULLSCREEN, DOUBLEBUF

DEBUG = False
CAPTION = "AudioVisual: keyboard"
SCREEN_SIZE = (1024, 640)
BACKGROUND_COLOR = (0, 0, 0)
VAMP_PLUGIN = "qm-vamp-plugins:qm-transcription"
#VAMP_PLUGIN = "silvet:silvet"
#VAMP_PLUGIN = "ua-vamp-plugins:mf0ua"

SAMPLE_RATE = 44100
CHANNELS = 2
BUFFER_SIZE = 2048


class Note(object):
    def __init__(self, _id, start_time, duration, midi):
        self.id, self.start_time, self.duration, self.midi = _id, start_time, duration, midi

    def __repr__(self):
        return "id=%d start_time=%.2f duration=%.2f midi=%d" % (self.id, self.start_time, self.duration, self.midi)

class NoteManager(object):
    def __init__(self):
        self.notes = []
        self.primed = False

    def add(self, note):
        self.notes.append(note)
        self.primed = False

    def prime(self):
        self.notes.sort(key=lambda note: -note.start_time)
        self.primed = True

    def pop_notes(self, curr_time):
        if not self.primed:
            self.prime()

        curr_notes = []
        while len(self.notes) > 0 and curr_time >= self.notes[-1].start_time:
            curr_notes.append(self.notes.pop())
        return curr_notes


def loadSound(filename, sample_rate, channels):
    FFMPEG_BIN = "ffmpeg"
    command = [ FFMPEG_BIN,
            '-i', filename,
            '-f', 's16le',
            '-acodec', 'pcm_s16le',
            '-ar', str(sample_rate),
            '-ac', str(channels),
            '-']
    if DEBUG: print command
    pipe = sp.Popen(command, stdout=sp.PIPE, bufsize=2**8)

    raw_audio = pipe.stdout.read() #88200*4)

    # Reorganize raw_audio as a Numpy array
    audio_array = numpy.fromstring(raw_audio, dtype="int16")

    return audio_array

# pygame seems unable to play at 44100 on my laptop and
# seems to need 22050
def startSound(audio_array, in_sample_rate, in_channels, out_sample_rate=22050, out_channels=2):
    import audioop

    audio_array2 = audioop.ratecv(audio_array, 2, in_channels, in_sample_rate, out_sample_rate, None)[0]
    if out_channels == 1:
        audio_array2 = audioop.tomono(audio_array2, 2, 0.5, 0.5)[0]
    audio_array3 = numpy.frombuffer(audio_array2, numpy.int16)

    if out_channels > 1:
        audio_array3 = audio_array3.reshape((len(audio_array3)/out_channels,out_channels))

    pg.mixer.init(frequency=out_sample_rate, size=-16, channels=out_channels)
    if DEBUG: print pg.mixer.get_init()
    sound = pg.sndarray.make_sound(audio_array3)
    playing = sound.play()    


def analyzeAudio(audio_array, sample_rate, channels):
    print "Found Vamp plugins:"
    for name in vamp.list_plugins():
        print "  " + name

    # convert audio array to float format expected by vamp
    audio_array2 = audio_array / float(numpy.iinfo(numpy.int16).max)
    audio_array2 = audio_array2.reshape((len(audio_array2)/channels,channels))[:,0]

    if False:
        # chuncked
        results = []
        for subarray in numpy.array_split(audio_array2, numpy.ceil(audio_array2.shape[0] / float(BUFFER_SIZE)), axis=0):
            if DEBUG: print "subarray size: " + str(subarray.shape[0])
            #assert(subarray.shape[0] == BUFFER_SIZE)
            results += [vamp.collect(subarray, sample_rate, VAMP_PLUGIN)]
    else:
        # all at once
        results = vamp.collect(audio_array2, sample_rate, VAMP_PLUGIN)
        if DEBUG: 
            print "Vamp plugin output:"
            for result in results["list"][:15]:
                print "  %s" % result

    results = [(float(row["timestamp"]), float(row["duration"]), int(row["values"][0])) for row in results["list"]]

    return results


class Sprite(object):
    def __init__(self, location, size, color, end_time, note):
        self.location, self.size, self.color, self.end_time, self.note = location, size, color, end_time, note
        self.rect = pg.Rect(location[0], location[1], size[0], size[1])

    def get_event(self, event, objects):
        if event.type == pg.KEYDOWN:
            if event.key == pg.K_SPACE:
                pass

    def update(self):
        pass

    def draw(self, surface, curr_time):
        #if DEBUG: print "  Drawing sprite: %s at %s" % (self.note, self.location)
        intensity = 1 - (curr_time - (self.end_time - self.note.duration)) / self.note.duration
        intensity = min(max(0, intensity), 255)
        #print "Note intensity: id=%d intensity=%.2f" % (self.note.id, intensity)
        color = (int(intensity * self.color[0]), int(intensity * self.color[1]), int(intensity * self.color[2]))
        return pg.draw.rect(surface, color, self.rect)

    def hasExpired(self, curr_time):
        return curr_time > self.end_time


class Control(object):
    def __init__(self, note_mgr):
        self.screen = pg.display.get_surface()
        self.screen_rect = self.screen.get_rect()
        self.done = False
        self.clock = pg.time.Clock()
        self.fps = 60.0
        self.sprites = []
        self.note_mgr = note_mgr
        self.start_time = pg.time.get_ticks() / 1000.0
        self.font = pg.font.SysFont("monospace", 18)

    def time(self):
        return pg.time.get_ticks() / 1000.0 - self.start_time

    def event_loop(self):
        for event in pg.event.get():
            self.keys = pg.key.get_pressed()
            if event.type == pg.QUIT or self.keys[pg.K_ESCAPE]:
                self.done = True

    def update(self):
        # update existing sprites
        anyExpired = False
        for sprite in self.sprites:
            sprite.update()
            if sprite.hasExpired(self.time()):
                anyExpired = True

        if anyExpired:
            if DEBUG: print "%.2fs Removing some sprites" % (self.time())
            self.sprites = [sprite for sprite in self.sprites if not sprite.hasExpired(self.time())]

        # add new sprites
        for note in self.note_mgr.pop_notes(self.time()):
            location = (int(self.screen.get_width() * note.midi / 110.0),  int(self.screen.get_height() / 2))
            size = (int(self.screen.get_width() / 110), 50)
            color = (255, 0, 0)
            sprite = Sprite(location, size, color, note.start_time + note.duration, note)
            self.sprites.append(sprite)
            print "%.2fs Adding sprite (n=%d): %s (with loc=%s size=%s)" % (len(self.sprites), self.time(), note, location, size)

    def draw(self):
        #self.screen.fill(BACKGROUND_COLOR)
        rects = []
        for sprite in self.sprites:
            rects += [sprite.draw(self.screen, self.time())]
        return rects

    def display_fps(self):
        caption = "{} - FPS: {:.2f}".format(CAPTION, self.clock.get_fps())
        pg.display.set_caption(caption)
        label = self.font.render("fps: %.0f" % self.clock.get_fps(), 1, (255,255,255))
        return self.screen.blit(label, (0, 0))

    def main_loop(self):
        background_surface = pg.Surface(self.screen_rect.size)
        background_surface.fill(BACKGROUND_COLOR)

        oldrects = []
        while not self.done:
            self.event_loop()
            self.update()
            rects = self.draw()
            fps_rect = self.display_fps()
            #pg.display.flip()
            pg.display.update(rects + oldrects + [fps_rect])
            for rect in rects + [fps_rect]:
                self.screen.blit(background_surface, rect, rect)
            oldrects = rects          
            self.clock.tick(self.fps)


if __name__ == "__main__":
    fn = sys.argv[1]

    pg.init()
    pg.display.set_caption(CAPTION)
    pg.display.set_mode(SCREEN_SIZE, DOUBLEBUF | FULLSCREEN)
    pg.display.get_surface().set_alpha(None)

    # load the sound
    snd = loadSound(fn, SAMPLE_RATE, CHANNELS)

    # analyze the sound and create the note manager
    notes = analyzeAudio(snd, SAMPLE_RATE, CHANNELS)
    note_mgr = NoteManager()
    for i, (start_time, duration, midi) in enumerate(notes):
        note_mgr.add(Note(i, start_time, duration, midi))

    # start playing the sound
    startSound(snd, SAMPLE_RATE, CHANNELS)

    # start the control loop
    control = Control(note_mgr)
    control.main_loop()
    pg.mixer.quit()
    pg.quit()
