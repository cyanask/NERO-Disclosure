// Local OCR only. No network, model credentials, or document mutation.
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count == 2 else { exit(2) }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = false
do {
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]), options: [:])
    try handler.perform([request])
    let rows = (request.results ?? []).compactMap { observation -> [String: Any]? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        return ["text": candidate.string, "confidence": candidate.confidence,
                "box": [observation.boundingBox.minX, observation.boundingBox.minY,
                        observation.boundingBox.width, observation.boundingBox.height]]
    }
    let data = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch { fputs("Local OCR failed\n", stderr); exit(1) }
