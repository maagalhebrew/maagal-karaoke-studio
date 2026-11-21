// Build on macOS with xcrun swiftc -parse-as-library -O -target <arch>-apple-macos13.0
// SystemAudioCapture.swift -o SystemAudioCapture. Package the executable next
// to capture_audio.py and sign it before signing the app bundle.
import AudioToolbox
import CoreGraphics
import CoreMedia
import Dispatch
import Darwin
import Foundation
import ScreenCaptureKit

private let rate = 48_000
private let channels = 2

private func report(_ kind: String, _ message: String) {
    let line = message.split(whereSeparator: \.isNewline).joined(separator: " ")
    FileHandle.standardError.write(Data("\(kind)\t\(line)\n".utf8))
}

private func fail(_ message: String) -> Never {
    report("ERROR", message)
    exit(EXIT_FAILURE)
}

private struct UnexpectedFormat: Error {}

private final class AudioOutput: NSObject, SCStreamOutput, SCStreamDelegate {
    func stream(_ stream: SCStream, didOutputSampleBuffer buffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, buffer.isValid, buffer.numSamples > 0 else { return }
        do {
            let pcm = try interleavedPCM(buffer)
            try FileHandle.standardOutput.write(contentsOf: pcm)
        } catch {
            fail("The Mac could not read the system audio stream. Restart playback and try again.")
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail("System audio capture stopped. Check your audio output and Screen Recording permission, then try again.")
    }

    private func interleavedPCM(_ buffer: CMSampleBuffer) throws -> Data {
        guard let format = buffer.formatDescription,
              let description = CMAudioFormatDescriptionGetStreamBasicDescription(format)?.pointee,
              description.mFormatID == kAudioFormatLinearPCM,
              description.mSampleRate == Double(rate) else { throw UnexpectedFormat() }
        let sourceChannels = Int(description.mChannelsPerFrame)
        let frames = buffer.numSamples
        let planar = description.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
        let floatingPoint = description.mFormatFlags & kAudioFormatFlagIsFloat != 0
        let signed = description.mFormatFlags & kAudioFormatFlagIsSignedInteger != 0
        guard sourceChannels == 1 || sourceChannels == channels,
              floatingPoint && description.mBitsPerChannel == 32 ||
                  !floatingPoint && signed && description.mBitsPerChannel == 16
        else { throw UnexpectedFormat() }

        return try buffer.withAudioBufferList(flags: [.audioBufferListAssure16ByteAlignment]) { list, _ in
            let requiredBuffers = planar ? sourceChannels : 1
            let elements = frames * (planar ? 1 : sourceChannels)
            let bytesPerElement = Int(description.mBitsPerChannel) / 8
            guard list.count == requiredBuffers,
                  list.allSatisfy({ $0.mData != nil && Int($0.mDataByteSize) >= elements * bytesPerElement })
            else { throw UnexpectedFormat() }
            var pcm = [Int16]()
            pcm.reserveCapacity(frames * channels)
            for frame in 0..<frames {
                for outputChannel in 0..<channels {
                    let channel = min(outputChannel, sourceChannels - 1)
                    let block = list[planar ? channel : 0].mData!
                    let index = planar ? frame : frame * sourceChannels + channel
                    if floatingPoint {
                        let sample = block.assumingMemoryBound(to: Float.self)[index]
                        let safe = sample.isFinite ? max(-1, min(1, sample)) : 0
                        pcm.append(Int16(safe * 32_767).littleEndian)
                    } else {
                        pcm.append(block.assumingMemoryBound(to: Int16.self)[index].littleEndian)
                    }
                }
            }
            return pcm.withUnsafeBufferPointer { Data(buffer: $0) }
        }
    }
}

@main
private struct SystemAudioCapture {
    static func main() async {
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            fail("Allow Karaoke IL in System Settings, under Privacy & Security → Screen & System Audio Recording (or Screen Recording). Reopen the app and try again.")
        }

        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first(where: { $0.displayID == CGMainDisplayID() }) ?? content.displays.first else {
                fail("A connected display is required to start system audio capture on this Mac.")
            }
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let configuration = SCStreamConfiguration()
            configuration.capturesAudio = true
            configuration.excludesCurrentProcessAudio = true
            configuration.sampleRate = rate
            configuration.channelCount = channels

            let audio = AudioOutput()
            let stream = SCStream(filter: filter, configuration: configuration, delegate: audio)
            try stream.addStreamOutput(audio, type: .audio, sampleHandlerQueue: DispatchQueue(label: "karaoke.audio.capture"))
            try await stream.startCapture()
            report("DEVICE", "macOS system audio")
            while true {
                // The parent controls the helper's lifetime and commits the WAV.
                try await Task.sleep(nanoseconds: 60_000_000_000)
                withExtendedLifetime((stream, audio)) {}
            }
        } catch {
            fail("macOS could not start system audio capture. Check your playback output and Screen Recording permission, then try again.")
        }
    }
}
