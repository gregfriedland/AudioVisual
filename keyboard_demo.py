import subprocess as sp
import numpy
import sys
import vamp
import pygame as pg
from pygame.locals import FULLSCREEN, DOUBLEBUF

DEBUG = False
CAPTION = "mp3-viz"
SCREEN_SIZE = (1024, 640)
BACKGROUND_COLOR = (0, 0, 0)

SAMPLE_RATE = 22050
CHANNELS = 2
BUFFER_SIZE = 2048

def pg_toggle_fullscreen():
    screen = pg.display.get_surface()
    tmp = screen.convert()
    caption = pg.display.get_caption()
    cursor = pg.mouse.get_cursor()  # Duoas 16-04-2007 
    
    w,h = screen.get_width(),screen.get_height()
    flags = screen.get_flags()
    bits = screen.get_bitsize()
    
    pg.display.quit()
    pg.display.init()
    
    screen = pg.display.set_mode((w,h),flags^FULLSCREEN,bits)
    screen.blit(tmp,(0,0))
    pg.display.set_caption(*caption)
 
    pg.key.set_mods(0) #HACK: work-a-round for a SDL bug??
 
    pg.mouse.set_cursor( *cursor )  # Duoas 16-04-2007
    
    return screen


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
        self.primed = False
        self.notes.append(note)

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


def startSound(audio_array, sample_rate, channels):
    audio_array = audio_array.reshape((len(audio_array)/channels,channels))

    pg.mixer.init(frequency=sample_rate, size=-16, channels=channels)
    if DEBUG: print pg.mixer.get_init()
    sound = pg.sndarray.make_sound( audio_array )
    playing = sound.play()    


def analyzeAudio(audio_array, sample_rate, channels):
    if DEBUG: print vamp.list_plugins()

    # import librosa    
    # audio_array3, sample_rate = librosa.load("/Users/gregfriedland/Downloads/8081.wav")
    # print "expected shape & range: %s, %f - %f" % (audio_array3.shape, audio_array3.min(), audio_array3.max())

    # convert audio array to float format expected by vamp
    audio_array2 = audio_array / float(numpy.iinfo(numpy.int16).max)
    audio_array2 = audio_array2.reshape((len(audio_array2)/channels,channels))[:,0]

    if False:
        results = []
        for subarray in numpy.array_split(audio_array2, numpy.ceil(audio_array2.shape[0] / float(BUFFER_SIZE)), axis=0):
            if DEBUG: print "subarray size: " + str(subarray.shape[0])
            #assert(subarray.shape[0] == BUFFER_SIZE)
            results += [vamp.collect(subarray, sample_rate, "qm-vamp-plugins:qm-transcription")]
    else:
        results = vamp.collect(audio_array2, sample_rate, "qm-vamp-plugins:qm-transcription")

    results = [(float(row["timestamp"]), float(row["duration"]), int(row["values"][0])) for row in results["list"]]

    return results


class Sprite(object):
    def __init__(self, location, size, color, end_time, note):
        self.location, self.size, self.color, self.end_time, self.note = location, size, color, end_time, note

    def get_event(self, event, objects):
        if event.type == pg.KEYDOWN:
            if event.key == pg.K_SPACE:
                pass # objects.add(Laser(self.rect.center, self.angle))

    def update(self):
        pass

    def draw(self, surface, curr_time):
        if DEBUG: print "  Drawing sprite: %s at %s" % (self.note, self.location)
        intensity = 1 - (curr_time - (self.end_time - self.note.duration)) / self.note.duration
        intensity = min(max(0, intensity), 255)
        #print "Note intensity: id=%d intensity=%.2f" % (self.note.id, intensity)
        color = (int(intensity * self.color[0]), int(intensity * self.color[1]), int(intensity * self.color[2]))
        pg.draw.rect(surface, color, (self.location[0], self.location[1], self.size[0], self.size[1]))

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
            print "%.2fs Adding sprite: %s (with loc=%s size=%s)" % (self.time(), note, location, size)

    def draw(self):
        self.screen.fill(BACKGROUND_COLOR)
        for sprite in self.sprites:
            sprite.draw(self.screen, self.time())

    def display_fps(self):
        caption = "{} - FPS: {:.2f}".format(CAPTION, self.clock.get_fps())
        #print caption
        pg.display.set_caption(caption)

    def main_loop(self):
        while not self.done:
            self.event_loop()
            self.update()
            self.draw()
            pg.display.flip()
            self.clock.tick(self.fps)
            self.display_fps()

if __name__ == "__main__":
    fn = sys.argv[1]

    pg.init()
    pg.display.set_caption(CAPTION)
    pg.display.set_mode(SCREEN_SIZE, FULLSCREEN | DOUBLEBUF)
    pg.display.get_surface().set_alpha(None)

    # load the sound and analyze it
    snd = loadSound(fn, SAMPLE_RATE, CHANNELS)
    notes = analyzeAudio(snd, SAMPLE_RATE, CHANNELS)

    # create the note manager
    note_mgr = NoteManager()
    for i, (start_time, duration, midi) in enumerate(notes):
        note_mgr.add(Note(i, start_time, duration, midi))

    startSound(snd, SAMPLE_RATE, CHANNELS)
    #pg_toggle_fullscreen()
    control = Control(note_mgr)
    control.main_loop()
    pg.mixer.quit()
    pg.quit()
