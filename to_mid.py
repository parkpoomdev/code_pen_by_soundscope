  # to_mid.py
  # Usage: py -3 to_mid.py
  from mido import Message, MidiFile, MidiTrack, MetaMessage, bpm2tempo

  def write_mid(outfile='output.mid', bpm=90, numer=4, denom=4):
      mid = MidiFile(type=0)  # single track
      mid.ticks_per_beat = 480
      track = MidiTrack(); mid.tracks.append(track)

      track.append(MetaMessage('set_tempo', tempo=bpm2tempo(bpm), time=0))
      track.append(MetaMessage('time_signature', numerator=numer, denominator=denom, clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
      track.append(MetaMessage('key_signature', key='C', time=0))
      track.append(MetaMessage('track_name', name='Chord Track', time=0))

      # Example: three chords, 1 bar each at numer beats per bar
      chords = [
          [50, 57, 62, 65, 69],   # Dm7
          [55, 59, 62, 67, 71],   # G7
          [48, 55, 59, 64, 71],   # Cmaj7
      ]
      chord_ticks = mid.ticks_per_beat * numer

      # Optional channel setup
      track.append(Message('control_change', channel=0, control=7, value=100, time=0))  # volume
      track.append(Message('program_change', channel=0, program=0, time=0))            # Acoustic Grand

      for chord in chords:
          for n in chord:
              track.append(Message('note_on', note=n, velocity=96, time=0))
          first = True
          for n in chord:
              track.append(Message('note_off', note=n, velocity=64, time=chord_ticks if first else 0))
              first = False

      track.append(MetaMessage('end_of_track', time=0))
      mid.save(outfile)
      print(f"Saved {outfile}")

  if __name__ == '__main__':
      write_mid('chords.mid', bpm=90, numer=4, denom=4)