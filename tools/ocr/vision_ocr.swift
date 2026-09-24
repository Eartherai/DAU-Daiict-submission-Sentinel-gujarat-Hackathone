// On-device text recognition with Apple Vision, for plate crops.
//
// Reads image paths, one per line, on stdin; writes one JSON line per image:
// {"path": ..., "candidates": [{"text": ..., "confidence": ...}, ...]}.
// Nothing leaves the machine: Vision runs on the Neural Engine / GPU locally.
// Language correction is off: a registration mark is not a word, and a
// dictionary would "correct" MH02 into something readable and wrong.
import Foundation
import Vision
import CoreImage

func recognise(_ path: String) -> [[String: Any]] {
    guard let img = CIImage(contentsOf: URL(fileURLWithPath: path)) else { return [] }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    req.recognitionLanguages = ["en-US"]
    req.minimumTextHeight = 0.2
    let handler = VNImageRequestHandler(ciImage: img, options: [:])
    do { try handler.perform([req]) } catch { return [] }
    var out: [[String: Any]] = []
    for obs in req.results ?? [] {
        for c in obs.topCandidates(5) {
            let b = obs.boundingBox
            out.append(["text": c.string, "confidence": c.confidence,
                        "box": [b.origin.x, b.origin.y, b.size.width, b.size.height]])
        }
    }
    return out
}

while let line = readLine() {
    let path = line.trimmingCharacters(in: .whitespaces)
    if path.isEmpty { continue }
    let res: [String: Any] = ["path": path, "candidates": recognise(path)]
    if let data = try? JSONSerialization.data(withJSONObject: res),
       let s = String(data: data, encoding: .utf8) {
        print(s)
        fflush(stdout)
    }
}
