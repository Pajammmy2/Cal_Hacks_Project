import Foundation
import CoreText
import CoreGraphics

/// Rule #4 (no mid-word wrap, any screen, any Dynamic Type size): SwiftUI only breaks inside a word when that single
/// word is wider than its column. `WordFit` measures the widest word of a string in the app's font at the size a
/// screen uses at AX5 and reports the scale the text would need to fit; a screen passes when that scale is within the
/// `minimumScaleFactor` it allows (1.0 when it allows none).
public enum WordFit {
    public static func font(url: URL, size: CGFloat) -> CTFont? {
        guard let descs = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor], let d = descs.first else { return nil }
        return CTFontCreateWithFontDescriptor(d, size, nil)
    }

    public static func width(_ word: String, font: CTFont) -> CGFloat {
        let attrs = [kCTFontAttributeName as NSAttributedString.Key: font]
        let line = CTLineCreateWithAttributedString(NSAttributedString(string: word, attributes: attrs))
        return CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
    }

    public static func widestWord(_ text: String, font: CTFont) -> (String, CGFloat) {
        var best = ("", CGFloat(0))
        for w in text.split(whereSeparator: { $0.isWhitespace || $0.isNewline }) {
            let x = width(String(w), font: font)
            if x > best.1 { best = (String(w), x) }
        }
        return best
    }

    /// Scale (<= 1) the text needs so its widest word fits `column` points; 1 when it already fits.
    public static func neededScale(_ text: String, font: CTFont, column: CGFloat) -> CGFloat {
        let (_, w) = widestWord(text, font: font)
        return w <= column ? 1 : column / w
    }
}
