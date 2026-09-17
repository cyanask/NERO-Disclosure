// Release helper: system PDFKit + Vision; no Xcode, network or model at runtime.
import Foundation
import AppKit
import PDFKit
import Vision

func recognize(_ image: CGImage) throws -> [[String: Any]] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    return (request.results ?? []).compactMap { item in
        guard let line = item.topCandidates(1).first else { return nil }
        return ["text": line.string, "confidence": line.confidence,
                "box": [item.boundingBox.minX, item.boundingBox.minY,
                        item.boundingBox.width, item.boundingBox.height]]
    }
}

func pageImage(_ page: PDFPage) throws -> CGImage {
    let bounds = page.bounds(for: .mediaBox)
    let scale = min(150.0 / 72.0, 4000.0 / max(bounds.width, bounds.height))
    guard bounds.width > 0, bounds.height > 0,
          let context = CGContext(data: nil, width: max(1, Int(bounds.width * scale)),
                                  height: max(1, Int(bounds.height * scale)), bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
        throw NSError(domain: "NERO OCR", code: 2)
    }
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: context.width, height: context.height))
    context.scaleBy(x: scale, y: scale)
    context.translateBy(x: -bounds.minX, y: -bounds.minY)
    page.draw(with: .mediaBox, to: context)
    guard let image = context.makeImage() else { throw NSError(domain: "NERO OCR", code: 3) }
    return image
}

do {
    let args = Array(CommandLine.arguments.dropFirst())
    if args == ["--version"] { print("NERO OCR 1.0 / Apple Vision + PDFKit"); exit(0) }
    let image: CGImage
    if args.count == 3 && args[0] == "--pdf-page" {
        guard let number = Int(args[2]), number > 0,
              let document = PDFDocument(url: URL(fileURLWithPath: args[1])),
              !document.isLocked, let page = document.page(at: number - 1) else {
            throw NSError(domain: "NERO OCR", code: 4)
        }
        image = try pageImage(page)
    } else if args.count == 1 {
        guard let source = NSImage(contentsOfFile: args[0]),
              let bitmap = source.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            throw NSError(domain: "NERO OCR", code: 5)
        }
        image = bitmap
    } else { throw NSError(domain: "NERO OCR", code: 6) }
    let result = try recognize(image)
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]))
} catch {
    fputs("文档图像无法识别，请核对原件或人工补核。\n", stderr)
    exit(1)
}
