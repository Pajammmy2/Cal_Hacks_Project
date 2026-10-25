import Testing
@testable import EmberApp

/// Navigate → Speak crashed the app (NSException from AVAudioEngine.installTap) whenever the microphone input
/// format was 0 Hz / 0 channels. The controller must refuse such a format and report "heard nothing" instead.
@Suite struct VoiceControllerMicFormatTests {
    @Test func zeroHertzOrNoChannelsIsNotUsable() {
        #expect(!VoiceController.micFormatIsUsable(sampleRate: 0, channels: 0))
        #expect(!VoiceController.micFormatIsUsable(sampleRate: 0, channels: 1))
        #expect(!VoiceController.micFormatIsUsable(sampleRate: 44_100, channels: 0))
    }

    @Test func realMicFormatsAreUsable() {
        #expect(VoiceController.micFormatIsUsable(sampleRate: 44_100, channels: 1))
        #expect(VoiceController.micFormatIsUsable(sampleRate: 48_000, channels: 2))
    }
}
