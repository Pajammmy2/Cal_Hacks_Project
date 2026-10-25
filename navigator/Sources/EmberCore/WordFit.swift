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
        for w in text.split(whereSeparator: { ($0.isWhitespace || $0.isNewline) && $0 != WordFit.nbsp }) {
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

    // MARK: Navigate strip ("130 m to next turn · 33 min to go")

    /// No-break space: a number and its unit are one word, so "710 m" never wraps as "710" / "m" at AX sizes.
    public static let nbsp: Character = "\u{00A0}"
    public static func stripValue(_ n: Int, unit: String) -> String { "\(n)\(nbsp)\(unit)" }

    /// Scale steps the strip tries (ViewThatFits) before its last shrink-to-fit layout; the last step is the
    /// `minimumScaleFactor` the texts allow, so what fits here never truncates.
    public static let stripScales: [CGFloat] = [1, 0.85, 0.7, 0.6]
    public static let stripBig: CGFloat = 26, stripSmall: CGFloat = 17, stripIconGap: CGFloat = 6, stripItemGap: CGFloat = 18
    public static let stripTrailingGap: CGFloat = 10
    /// Cap of the value font at accessibility sizes (uncapped title2 reaches 66 pt at AX5).
    public static let stripBigAXCap: CGFloat = 48

    /// Width of the strip at `scale` with the layout's own metrics: per item an SF icon (≈ 1.1 em of the caption
    /// font), the value in the big font and the caption in the small one; `trailing` is the control at the end.
    public static func stripWidth(items: [(value: String, caption: String)], fontURL: URL, scale: CGFloat, trailing: CGFloat) -> CGFloat? {
        guard let big = font(url: fontURL, size: stripBig * scale), let small = font(url: fontURL, size: stripSmall * scale) else { return nil }
        var total: CGFloat = 0
        for (i, it) in items.enumerated() {
            if i > 0 { total += stripItemGap }
            total += stripSmall * scale * 1.1 + stripIconGap + width(it.value, font: big) + stripIconGap + width(it.caption, font: small)
        }
        if trailing > 0 { total += stripTrailingGap + trailing }
        return total
    }

    /// The first strip scale at which everything fits `column` whole, nil when even the smallest step overflows.
    public static func stripScale(items: [(value: String, caption: String)], fontURL: URL, column: CGFloat, trailing: CGFloat) -> CGFloat? {
        stripScales.first { s in (stripWidth(items: items, fontURL: fontURL, scale: s, trailing: trailing) ?? .infinity) <= column }
    }
}
