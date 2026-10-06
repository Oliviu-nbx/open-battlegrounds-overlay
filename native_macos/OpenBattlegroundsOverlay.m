#import <Cocoa/Cocoa.h>

static NSString *OBString(id value) {
    return (!value || value == [NSNull null]) ? @"—" : [value description];
}

static NSString *OBPercentage(id value) {
    if (!value || value == [NSNull null]) return @"—";
    return [NSString stringWithFormat:@"%.1f%%", [value doubleValue] * 100.0];
}

static NSString *OBNumberRange(NSArray *values) {
    if (![values isKindOfClass:[NSArray class]] || values.count == 0) return @"—";
    NSMutableArray<NSString *> *parts = [NSMutableArray array];
    for (id value in values) [parts addObject:OBString(value)];
    return [parts componentsJoinedByString:@"–"];
}

@interface GameOverlayPanel : NSPanel
@end

@implementation GameOverlayPanel
- (BOOL)canBecomeKey { return YES; }
- (BOOL)canBecomeMain { return NO; }
@end

@interface CombatOddsView : NSView
@property(nonatomic, copy) NSString *title;
@property(nonatomic, copy) NSString *detail;
@property(nonatomic, copy) NSString *stage;
@property(nonatomic, strong) NSNumber *win;
@property(nonatomic, strong) NSNumber *tie;
@property(nonatomic, strong) NSNumber *loss;
@property(nonatomic) BOOL ready;
@property(nonatomic) BOOL baseline;
@end

@implementation CombatOddsView

- (instancetype)initWithFrame:(NSRect)frame {
    self = [super initWithFrame:frame];
    if (!self) return nil;
    self.wantsLayer = YES;
    _title = @"COMBAT ODDS";
    _detail = @"Waiting for revealed boards";
    _stage = @"LOCAL MODEL";
    return self;
}

- (void)drawString:(NSString *)string in:(NSRect)rect font:(NSFont *)font color:(NSColor *)color alignment:(NSTextAlignment)alignment {
    NSMutableParagraphStyle *style = [NSMutableParagraphStyle new];
    style.alignment = alignment;
    style.lineBreakMode = NSLineBreakByTruncatingTail;
    [string drawInRect:rect withAttributes:@{NSFontAttributeName: font, NSForegroundColorAttributeName: color,
                                               NSParagraphStyleAttributeName: style}];
}

- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];
    NSRect bounds = NSInsetRect(self.bounds, 1, 1);
    NSColor *surface = [NSColor colorWithCalibratedRed:0.055 green:0.061 blue:0.083 alpha:0.98];
    NSColor *violet = [NSColor colorWithCalibratedRed:0.61 green:0.25 blue:0.88 alpha:0.95];
    NSColor *gold = [NSColor colorWithCalibratedRed:0.88 green:0.66 blue:0.27 alpha:1.0];
    NSColor *muted = [NSColor colorWithCalibratedRed:0.66 green:0.69 blue:0.77 alpha:1.0];
    NSBezierPath *panel = [NSBezierPath bezierPathWithRoundedRect:bounds xRadius:7 yRadius:7];
    [surface setFill]; [panel fill];
    [violet setStroke]; panel.lineWidth = 1.25; [panel stroke];
    [gold setFill]; [[NSBezierPath bezierPathWithRect:NSMakeRect(NSMinX(bounds), NSMaxY(bounds) - 3, NSWidth(bounds), 3)] fill];

    [self drawString:self.title.uppercaseString in:NSMakeRect(12, NSMaxY(bounds) - 27, 190, 15)
                font:[NSFont systemFontOfSize:10 weight:NSFontWeightBold] color:NSColor.whiteColor alignment:NSTextAlignmentLeft];
    NSString *tag = self.baseline ? @"BASELINE" : self.ready ? self.stage.uppercaseString : @"AWAITING DATA";
    [self drawString:tag in:NSMakeRect(NSMaxX(bounds) - 132, NSMaxY(bounds) - 27, 120, 15)
                font:[NSFont monospacedSystemFontOfSize:9 weight:NSFontWeightBold] color:self.baseline ? gold : violet alignment:NSTextAlignmentRight];
    [[NSColor colorWithCalibratedRed:0.20 green:0.22 blue:0.29 alpha:1] setFill];
    [[NSBezierPath bezierPathWithRect:NSMakeRect(NSMinX(bounds) + 1, NSMaxY(bounds) - 35, NSWidth(bounds) - 2, 1)] fill];

    if (!self.ready) {
        [self drawString:self.detail ?: @"Waiting for local combat data" in:NSMakeRect(14, 17, NSWidth(bounds) - 28, 38)
                    font:[NSFont systemFontOfSize:11 weight:NSFontWeightMedium] color:muted alignment:NSTextAlignmentCenter];
        return;
    }
    NSArray<NSString *> *labels = @[@"WIN", @"TIE", @"LOSS"];
    NSArray<NSNumber *> *values = @[self.win ?: @0, self.tie ?: @0, self.loss ?: @0];
    NSArray<NSColor *> *colors = @[[NSColor colorWithCalibratedRed:0.53 green:0.92 blue:0.48 alpha:1],
                                   [NSColor colorWithCalibratedRed:0.79 green:0.74 blue:0.95 alpha:1],
                                   [NSColor colorWithCalibratedRed:1.0 green:0.52 blue:0.50 alpha:1]];
    CGFloat width = NSWidth(bounds) / 3.0;
    for (NSUInteger index = 0; index < labels.count; index++) {
        CGFloat x = NSMinX(bounds) + width * index;
        if (index) {
            [[NSColor colorWithCalibratedRed:0.20 green:0.22 blue:0.29 alpha:1] setFill];
            [[NSBezierPath bezierPathWithRect:NSMakeRect(x, 11, 1, NSHeight(bounds) - 47)] fill];
        }
        [self drawString:labels[index] in:NSMakeRect(x + 4, 57, width - 8, 14)
                    font:[NSFont systemFontOfSize:10 weight:NSFontWeightBold] color:colors[index] alignment:NSTextAlignmentCenter];
        [self drawString:OBPercentage(values[index]) in:NSMakeRect(x + 4, 22, width - 8, 31)
                    font:[NSFont monospacedSystemFontOfSize:24 weight:NSFontWeightBold] color:NSColor.whiteColor alignment:NSTextAlignmentCenter];
    }
}
@end

@interface OverlayContentView : NSView
@property(nonatomic, strong) NSTextField *titleLabel;
@property(nonatomic, strong) NSTextField *subtitleLabel;
@property(nonatomic, strong) NSTextField *resourcesLabel;
@property(nonatomic, strong) CombatOddsView *oddsView;
@property(nonatomic, strong) NSTextView *textView;
@end

@implementation OverlayContentView

- (instancetype)initWithFrame:(NSRect)frame {
    self = [super initWithFrame:frame];
    if (!self) return nil;
    self.wantsLayer = YES;
    self.layer.backgroundColor = [NSColor colorWithCalibratedRed:0.028 green:0.031 blue:0.047 alpha:0.95].CGColor;
    self.layer.borderColor = [NSColor colorWithCalibratedRed:0.44 green:0.17 blue:0.65 alpha:0.92].CGColor;
    self.layer.borderWidth = 1.0;
    self.layer.cornerRadius = 8.0;

    _titleLabel = [NSTextField labelWithString:@"OPEN BATTLEGROUNDS"];
    _titleLabel.font = [NSFont monospacedSystemFontOfSize:12 weight:NSFontWeightBold];
    _titleLabel.textColor = NSColor.whiteColor;
    _titleLabel.translatesAutoresizingMaskIntoConstraints = NO;
    [self addSubview:_titleLabel];

    _subtitleLabel = [NSTextField labelWithString:@"Reading local Power.log…"];
    _subtitleLabel.font = [NSFont systemFontOfSize:10 weight:NSFontWeightRegular];
    _subtitleLabel.textColor = [NSColor colorWithWhite:0.72 alpha:1];
    _subtitleLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    _subtitleLabel.translatesAutoresizingMaskIntoConstraints = NO;
    [self addSubview:_subtitleLabel];

    _resourcesLabel = [NSTextField labelWithString:@"TIER —    GOLD —    HP —    ARMOR —"];
    _resourcesLabel.font = [NSFont monospacedSystemFontOfSize:10 weight:NSFontWeightBold];
    _resourcesLabel.textColor = [NSColor colorWithCalibratedRed:0.88 green:0.66 blue:0.27 alpha:1.0];
    _resourcesLabel.translatesAutoresizingMaskIntoConstraints = NO;
    [self addSubview:_resourcesLabel];

    _oddsView = [[CombatOddsView alloc] initWithFrame:NSZeroRect];
    _oddsView.translatesAutoresizingMaskIntoConstraints = NO;
    [self addSubview:_oddsView];

    _textView = [[NSTextView alloc] initWithFrame:NSZeroRect];
    _textView.editable = NO;
    _textView.selectable = NO;
    _textView.drawsBackground = NO;
    _textView.textContainerInset = NSMakeSize(5, 5);
    _textView.textContainer.lineFragmentPadding = 0;

    NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSZeroRect];
    scroll.documentView = _textView;
    scroll.hasVerticalScroller = YES;
    scroll.drawsBackground = NO;
    scroll.borderType = NSNoBorder;
    scroll.translatesAutoresizingMaskIntoConstraints = NO;
    [self addSubview:scroll];

    [NSLayoutConstraint activateConstraints:@[
        [_titleLabel.topAnchor constraintEqualToAnchor:self.topAnchor constant:10],
        [_titleLabel.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:12],
        [_titleLabel.trailingAnchor constraintLessThanOrEqualToAnchor:self.trailingAnchor constant:-12],
        [_subtitleLabel.topAnchor constraintEqualToAnchor:_titleLabel.bottomAnchor constant:2],
        [_subtitleLabel.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:12],
        [_subtitleLabel.trailingAnchor constraintLessThanOrEqualToAnchor:self.trailingAnchor constant:-12],
        [_resourcesLabel.topAnchor constraintEqualToAnchor:_subtitleLabel.bottomAnchor constant:8],
        [_resourcesLabel.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:12],
        [_resourcesLabel.trailingAnchor constraintLessThanOrEqualToAnchor:self.trailingAnchor constant:-12],
        [_oddsView.topAnchor constraintEqualToAnchor:_resourcesLabel.bottomAnchor constant:8],
        [_oddsView.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:10],
        [_oddsView.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-10],
        [_oddsView.heightAnchor constraintEqualToConstant:108],
        [scroll.topAnchor constraintEqualToAnchor:_oddsView.bottomAnchor constant:6],
        [scroll.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:10],
        [scroll.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-10],
        [scroll.bottomAnchor constraintEqualToAnchor:self.bottomAnchor constant:-9]
    ]];
    [self renderWaiting];
    return self;
}

- (void)append:(NSString *)line font:(NSFont *)font color:(NSColor *)color to:(NSMutableAttributedString *)content {
    NSDictionary *attributes = @{NSFontAttributeName: font, NSForegroundColorAttributeName: color};
    [content appendAttributedString:[[NSAttributedString alloc] initWithString:[line stringByAppendingString:@"\n"] attributes:attributes]];
}

- (NSString *)minionLine:(NSDictionary *)minion {
    NSString *name = OBString(minion[@"name"]);
    NSString *attack = OBString(minion[@"attack"]);
    NSString *health = OBString(minion[@"health"]);
    NSArray *keywords = [minion[@"keywords"] isKindOfClass:[NSArray class]] ? minion[@"keywords"] : @[];
    NSString *suffix = keywords.count ? [NSString stringWithFormat:@"  [%@]", [keywords componentsJoinedByString:@", "]] : @"";
    return [NSString stringWithFormat:@"◈  %@\n     %@ ATK   ·   %@ HP%@", name, attack, health, suffix];
}

- (void)renderWaiting {
    self.subtitleLabel.stringValue = @"Starting native always-on-top overlay…";
    self.resourcesLabel.stringValue = @"TIER —    GOLD —    HP —    ARMOR —";
    self.oddsView.ready = NO;
    self.oddsView.baseline = NO;
    self.oddsView.title = @"COMBAT ODDS";
    self.oddsView.detail = @"Waiting for revealed local combat boards";
    self.oddsView.stage = @"LOCAL MODEL";
    [self.oddsView setNeedsDisplay:YES];
    NSMutableAttributedString *content = [NSMutableAttributedString new];
    [self append:@"LOCAL READ-ONLY OVERLAY" font:[NSFont systemFontOfSize:11 weight:NSFontWeightBold] color:[NSColor colorWithCalibratedRed:0.77 green:0.62 blue:1 alpha:1] to:content];
    [self append:@"This panel follows local Power.log data only. It never controls Hearthstone or exposes hidden opponent boards." font:[NSFont systemFontOfSize:11] color:NSColor.lightGrayColor to:content];
    [self.textView.textStorage setAttributedString:content];
}

- (void)renderFeed:(NSDictionary *)feed {
    NSString *phase = [OBString(feed[@"phase"]) uppercaseString];
    self.subtitleLabel.stringValue = [NSString stringWithFormat:@"R%@ · %@ · local, read-only", OBString(feed[@"round"]), phase];
    NSMutableAttributedString *content = [NSMutableAttributedString new];
    NSFont *heading = [NSFont systemFontOfSize:13 weight:NSFontWeightBold];
    NSFont *body = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
    NSFont *detail = [NSFont systemFontOfSize:10 weight:NSFontWeightRegular];
    NSColor *primary = NSColor.whiteColor;
    NSColor *secondary = [NSColor colorWithWhite:0.76 alpha:1];
    NSColor *warning = [NSColor colorWithCalibratedRed:1.0 green:0.80 blue:0.43 alpha:1];

    NSDictionary *odds = [feed[@"odds"] isKindOfClass:[NSDictionary class]] ? feed[@"odds"] : @{};
    self.resourcesLabel.stringValue = [NSString stringWithFormat:@"TIER %@    GOLD %@    HP %@    ARMOR %@", OBString(feed[@"tier"]), OBString(feed[@"gold"]), OBString(feed[@"health"]), OBString(feed[@"armor"])];
    BOOL ready = [odds[@"state"] isEqualToString:@"ready"];
    self.oddsView.ready = ready;
    self.oddsView.baseline = [odds[@"baseline"] boolValue];
    self.oddsView.title = ready ? @"COMBAT ODDS · CURRENT FIGHT" : OBString(odds[@"title"]);
    self.oddsView.detail = OBString(odds[@"detail"]);
    self.oddsView.stage = ready ? ([odds[@"stage"] isEqualToString:@"quick"] ? @"QUICK" : @"REFINED") : @"LOCAL MODEL";
    self.oddsView.win = ready ? odds[@"win"] : nil;
    self.oddsView.tie = ready ? odds[@"tie"] : nil;
    self.oddsView.loss = ready ? odds[@"loss"] : nil;
    [self.oddsView setNeedsDisplay:YES];

    if (ready) {
        NSString *fidelity = self.oddsView.baseline ? @"MODEL FIDELITY · INCOMPLETE BASELINE" : @"MODEL FIDELITY · FULL COVERAGE";
        [self append:fidelity font:[NSFont systemFontOfSize:10 weight:NSFontWeightBold] color:self.oddsView.baseline ? warning : [NSColor colorWithCalibratedRed:0.53 green:0.92 blue:0.48 alpha:1] to:content];
        [self append:[odds[@"stage"] isEqualToString:@"quick"] ? @"Quick estimate · refining in the background" : @"Refined local simulation" font:detail color:secondary to:content];
        if ([odds[@"baseline"] boolValue]) {
            [self append:@"Observed effects listed below are excluded from the model." font:detail color:warning to:content];
            NSArray *blockers = [odds[@"blockers"] isKindOfClass:[NSArray class]] ? odds[@"blockers"] : @[];
            for (NSUInteger index = 0; index < MIN((NSUInteger)2, blockers.count); index++) [self append:[@"• " stringByAppendingString:OBString(blockers[index])] font:detail color:warning to:content];
            if (blockers.count > 2) [self append:[NSString stringWithFormat:@"• %lu additional effects", (unsigned long)(blockers.count - 2)] font:detail color:warning to:content];
        }
        NSArray *interval = [odds[@"interval"] isKindOfClass:[NSArray class]] ? odds[@"interval"] : @[];
        if (interval.count == 2) [self append:[NSString stringWithFormat:@"%@ confidence · 95%% win interval %@–%@", OBString(odds[@"confidence"]), OBPercentage(interval[0]), OBPercentage(interval[1])] font:detail color:secondary to:content];
        if (odds[@"first_attacker"]) [self append:OBString(odds[@"first_attacker"]) font:detail color:secondary to:content];
        if (odds[@"dealt"] && odds[@"dealt"] != [NSNull null]) [self append:[NSString stringWithFormat:@"Conditional deal damage: %@", OBNumberRange(odds[@"dealt"])] font:detail color:secondary to:content];
        if (odds[@"received"] && odds[@"received"] != [NSNull null]) [self append:[NSString stringWithFormat:@"Conditional receive damage: %@", OBNumberRange(odds[@"received"])] font:detail color:secondary to:content];
        NSArray *scenario = [odds[@"scenario"] isKindOfClass:[NSArray class]] ? odds[@"scenario"] : @[];
        if (scenario.count == 2) {
            [self append:[NSString stringWithFormat:@"Stale-board sensitivity: %@–%@", OBPercentage(scenario[0]), OBPercentage(scenario[1])] font:detail color:warning to:content];
            [self append:OBString(odds[@"scenario_detail"]) font:detail color:secondary to:content];
        }
    } else {
        BOOL unavailable = [odds[@"state"] isEqualToString:@"unavailable"];
        [self append:@"COMBAT MODEL STATUS" font:[NSFont systemFontOfSize:10 weight:NSFontWeightBold] color:unavailable ? warning : secondary to:content];
        [self append:OBString(odds[@"detail"]) font:detail color:unavailable ? warning : secondary to:content];
        NSArray *blockers = [odds[@"blockers"] isKindOfClass:[NSArray class]] ? odds[@"blockers"] : @[];
        for (NSString *blocker in blockers) [self append:[@"• " stringByAppendingString:blocker] font:detail color:warning to:content];
    }
    NSArray *modelled = [odds[@"modelled"] isKindOfClass:[NSArray class]] ? odds[@"modelled"] : @[];
    if (modelled.count) {
        [self append:@"MODELLED" font:[NSFont systemFontOfSize:10 weight:NSFontWeightBold] color:secondary to:content];
        for (NSString *effect in modelled) [self append:[@"• " stringByAppendingString:effect] font:detail color:secondary to:content];
    }
    NSArray *factors = [feed[@"combat_factors"] isKindOfClass:[NSArray class]] ? feed[@"combat_factors"] : @[];
    if (factors.count) {
        [self append:@"FIGHT FACTORS · OBSERVED ONLY" font:[NSFont systemFontOfSize:10 weight:NSFontWeightBold] color:secondary to:content];
        for (NSUInteger index = 0; index < MIN((NSUInteger)3, factors.count); index++) [self append:[@"• " stringByAppendingString:OBString(factors[index])] font:detail color:secondary to:content];
    }

    NSDictionary *opponent = [feed[@"opponent"] isKindOfClass:[NSDictionary class]] ? feed[@"opponent"] : @{};
    [self append:@"" font:detail color:secondary to:content];
    [self append:[NSString stringWithFormat:@"OPPONENT · %@", [OBString(opponent[@"name"]) uppercaseString]] font:heading color:primary to:content];
    if (opponent[@"seen_round"] && opponent[@"seen_round"] != [NSNull null]) {
        NSString *age = opponent[@"age"] && opponent[@"age"] != [NSNull null] ? [NSString stringWithFormat:@" · %@ rounds old", OBString(opponent[@"age"])] : @"";
        [self append:[NSString stringWithFormat:@"Seen R%@%@ · may have changed", OBString(opponent[@"seen_round"]), age] font:detail color:warning to:content];
    } else {
        [self append:@"No dated board observation." font:detail color:warning to:content];
    }
    NSArray *threat = [opponent[@"threat"] isKindOfClass:[NSArray class]] ? opponent[@"threat"] : @[];
    for (NSString *signal in threat) [self append:[@"• " stringByAppendingString:signal] font:detail color:warning to:content];

    NSArray *plan = [feed[@"recruit_plan"] isKindOfClass:[NSArray class]] ? feed[@"recruit_plan"] : @[];
    if ([feed[@"phase"] isEqualToString:@"recruit"] && plan.count) {
        [self append:@"" font:detail color:secondary to:content];
        [self append:@"RECRUIT PLAN · HEURISTIC" font:heading color:primary to:content];
        for (NSUInteger index = 0; index < MIN((NSUInteger)8, plan.count); index++) [self append:OBString(plan[index]) font:detail color:secondary to:content];
    }

    [self append:@"" font:detail color:secondary to:content];
    [self append:@"YOUR BOARD" font:heading color:primary to:content];
    NSArray *board = [feed[@"board"] isKindOfClass:[NSArray class]] ? feed[@"board"] : @[];
    if (board.count == 0) [self append:@"No observed minions yet." font:detail color:secondary to:content];
    for (NSDictionary *minion in board) [self append:[self minionLine:minion] font:body color:primary to:content];

    if ([feed[@"phase"] isEqualToString:@"combat"]) {
        [self append:@"" font:detail color:secondary to:content];
        [self append:@"OPPONENT BOARD · LAST OBSERVED" font:heading color:primary to:content];
        NSArray *enemy = [opponent[@"board"] isKindOfClass:[NSArray class]] ? opponent[@"board"] : @[];
        for (NSDictionary *minion in enemy) [self append:[self minionLine:minion] font:body color:primary to:content];
    }
    [self append:@"" font:detail color:secondary to:content];
    [self append:[NSString stringWithFormat:@"%@\nUse the BG menu-bar item for Settings, hide/show and Quit.", OBString(feed[@"status"])] font:detail color:secondary to:content];
    [self.textView.textStorage setAttributedString:content];
    [self.textView scrollToBeginningOfDocument:nil];
}
@end

@interface AppDelegate : NSObject <NSApplicationDelegate, NSMenuDelegate>
@property(nonatomic, strong) GameOverlayPanel *panel;
@property(nonatomic, strong) OverlayContentView *content;
@property(nonatomic, strong) NSTimer *pollTimer;
@property(nonatomic, strong) NSTask *backend;
@property(nonatomic, strong) NSURL *stateURL;
@property(nonatomic, strong) NSURL *dataDirectory;
@property(nonatomic, strong) NSData *lastData;
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, strong) NSMenu *statusMenu;
@property(nonatomic, strong) NSMenu *commandMenu;
@property(nonatomic, strong) NSWindow *settingsWindow;
@property(nonatomic, strong) NSButton *alwaysOnTopControl;
@property(nonatomic) BOOL alwaysOnTop;
@end

@implementation AppDelegate

- (NSString *)argumentNamed:(NSString *)name {
    NSArray<NSString *> *arguments = NSProcessInfo.processInfo.arguments;
    NSUInteger index = [arguments indexOfObject:name];
    return (index != NSNotFound && index + 1 < arguments.count) ? arguments[index + 1] : nil;
}

- (NSURL *)applicationDataDirectory {
    NSURL *support = [[NSFileManager defaultManager] URLsForDirectory:NSApplicationSupportDirectory
                                                              inDomains:NSUserDomainMask].firstObject;
    NSURL *directory = [support URLByAppendingPathComponent:@"OpenBattlegroundsOverlay" isDirectory:YES];
    [[NSFileManager defaultManager] createDirectoryAtURL:directory withIntermediateDirectories:YES attributes:nil error:nil];
    NSURL *cards = [directory URLByAppendingPathComponent:@"cards.json"];
    NSURL *seed = [[[NSBundle mainBundle] resourceURL] URLByAppendingPathComponent:@"tracker_seed/data/cards.json"];
    if (![[NSFileManager defaultManager] fileExistsAtPath:cards.path]
        && [[NSFileManager defaultManager] fileExistsAtPath:seed.path]) {
        [[NSFileManager defaultManager] copyItemAtURL:seed toURL:cards error:nil];
    }
    return directory;
}

- (NSString *)pythonExecutable {
    NSString *specified = [self argumentNamed:@"--python"];
    if (specified.length) return specified;
    NSString *embedded = [[[NSBundle mainBundle] resourceURL] URLByAppendingPathComponent:@"python-runtime/bin/python3"].path;
    if ([[NSFileManager defaultManager] isExecutableFileAtPath:embedded]) return embedded;
    NSArray<NSString *> *candidates = @[@"/opt/homebrew/bin/python3", @"/usr/local/bin/python3",
        @"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3", @"/usr/bin/python3"];
    for (NSString *candidate in candidates) {
        if ([[NSFileManager defaultManager] isExecutableFileAtPath:candidate]) return candidate;
    }
    return @"/usr/bin/python3";
}

- (void)addCommandsToMenu:(NSMenu *)menu includeQuit:(BOOL)includeQuit {
    NSMenuItem *toggle = [[NSMenuItem alloc] initWithTitle:@"Hide Overlay" action:@selector(toggleOverlay:) keyEquivalent:@"o"];
    toggle.target = self;
    toggle.tag = 1001;
    [menu addItem:toggle];
    NSMenuItem *topmost = [[NSMenuItem alloc] initWithTitle:@"Keep Above Games" action:@selector(toggleAlwaysOnTop:) keyEquivalent:@""];
    topmost.target = self;
    topmost.tag = 1002;
    [menu addItem:topmost];
    NSMenuItem *settings = [[NSMenuItem alloc] initWithTitle:@"Settings…" action:@selector(showSettings:) keyEquivalent:@","];
    settings.target = self;
    [menu addItem:settings];
    NSMenuItem *reset = [[NSMenuItem alloc] initWithTitle:@"Move Overlay to Screen Edge" action:@selector(resetOverlayPosition:) keyEquivalent:@""];
    reset.target = self;
    [menu addItem:reset];
    if (includeQuit) {
        [menu addItem:[NSMenuItem separatorItem]];
        NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"Quit Open Battlegrounds Overlay" action:@selector(terminate:) keyEquivalent:@"q"];
        quit.target = NSApp;
        [menu addItem:quit];
    }
}

- (void)installMenus {
    self.statusItem = [[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
    self.statusItem.button.title = @"BG";
    self.statusItem.button.toolTip = @"Open Battlegrounds Overlay";
    self.statusMenu = [[NSMenu alloc] initWithTitle:@"Open Battlegrounds Overlay"];
    self.statusMenu.delegate = self;
    [self addCommandsToMenu:self.statusMenu includeQuit:YES];
    self.statusItem.menu = self.statusMenu;

    NSMenu *main = [[NSMenu alloc] initWithTitle:@"Main"];
    NSMenuItem *root = [[NSMenuItem alloc] initWithTitle:@"Open Battlegrounds Overlay" action:nil keyEquivalent:@""];
    self.commandMenu = [[NSMenu alloc] initWithTitle:@"Open Battlegrounds Overlay"];
    self.commandMenu.delegate = self;
    [self addCommandsToMenu:self.commandMenu includeQuit:YES];
    root.submenu = self.commandMenu;
    [main addItem:root];
    [NSApp setMainMenu:main];
}

- (void)menuWillOpen:(NSMenu *)menu {
    for (NSMenuItem *item in menu.itemArray) {
        if (item.tag == 1001) item.title = self.panel.visible ? @"Hide Overlay" : @"Show Overlay";
        if (item.tag == 1002) item.state = self.alwaysOnTop ? NSControlStateValueOn : NSControlStateValueOff;
    }
}

- (void)applyAlwaysOnTop {
    self.panel.level = self.alwaysOnTop ? NSScreenSaverWindowLevel : NSFloatingWindowLevel;
    self.panel.floatingPanel = self.alwaysOnTop;
    self.panel.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary | NSWindowCollectionBehaviorIgnoresCycle;
    self.alwaysOnTopControl.state = self.alwaysOnTop ? NSControlStateValueOn : NSControlStateValueOff;
}

- (void)toggleOverlay:(id)sender {
    if (self.panel.visible) [self.panel orderOut:nil];
    else {
        [self.panel orderFrontRegardless];
        [NSApp activateIgnoringOtherApps:YES];
    }
}

- (void)toggleAlwaysOnTop:(id)sender {
    self.alwaysOnTop = !self.alwaysOnTop;
    [[NSUserDefaults standardUserDefaults] setBool:self.alwaysOnTop forKey:@"alwaysOnTop"];
    [self applyAlwaysOnTop];
}

- (void)resetOverlayPosition:(id)sender {
    NSScreen *targetScreen = self.panel.screen ?: NSScreen.mainScreen;
    NSRect screen = targetScreen.visibleFrame;
    NSRect frame = self.panel.frame;
    [self.panel setFrameOrigin:NSMakePoint(NSMaxX(screen) - frame.size.width - 16, NSMaxY(screen) - frame.size.height - 24)];
    [self.panel orderFrontRegardless];
}

- (void)showSettings:(id)sender {
    [NSApp activateIgnoringOtherApps:YES];
    if (!self.settingsWindow) {
        self.settingsWindow = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 390, 205)
                                                           styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable)
                                                             backing:NSBackingStoreBuffered defer:NO];
        self.settingsWindow.title = @"Overlay Settings";
        self.settingsWindow.releasedWhenClosed = NO;
        NSView *content = self.settingsWindow.contentView;
        NSTextField *heading = [NSTextField labelWithString:@"Open Battlegrounds Overlay"];
        heading.font = [NSFont systemFontOfSize:16 weight:NSFontWeightSemibold];
        heading.frame = NSMakeRect(22, 158, 346, 24);
        [content addSubview:heading];
        NSTextField *description = [NSTextField wrappingLabelWithString:@"Use these controls when the game is focused. The overlay reads local tracker data only and never controls Hearthstone."];
        description.textColor = NSColor.secondaryLabelColor;
        description.font = [NSFont systemFontOfSize:12];
        description.frame = NSMakeRect(22, 112, 346, 38);
        [content addSubview:description];
        self.alwaysOnTopControl = [NSButton checkboxWithTitle:@"Keep overlay above compatible full-screen games" target:self action:@selector(toggleAlwaysOnTop:)];
        self.alwaysOnTopControl.frame = NSMakeRect(18, 75, 350, 24);
        [content addSubview:self.alwaysOnTopControl];
        NSButton *move = [NSButton buttonWithTitle:@"Move to Screen Edge" target:self action:@selector(resetOverlayPosition:)];
        move.frame = NSMakeRect(22, 25, 145, 32);
        [content addSubview:move];
        NSButton *hide = [NSButton buttonWithTitle:@"Hide Overlay" target:self action:@selector(toggleOverlay:)];
        hide.frame = NSMakeRect(176, 25, 105, 32);
        [content addSubview:hide];
        NSButton *quit = [NSButton buttonWithTitle:@"Quit" target:NSApp action:@selector(terminate:)];
        quit.frame = NSMakeRect(291, 25, 75, 32);
        [content addSubview:quit];
    }
    [self applyAlwaysOnTop];
    [self.settingsWindow center];
    [self.settingsWindow makeKeyAndOrderFront:nil];
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!self.panel.visible) [self.panel orderFrontRegardless];
    [NSApp activateIgnoringOtherApps:YES];
    return YES;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    if (![[NSUserDefaults standardUserDefaults] objectForKey:@"alwaysOnTop"])
        [[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"alwaysOnTop"];
    self.alwaysOnTop = [[NSUserDefaults standardUserDefaults] boolForKey:@"alwaysOnTop"];
    NSString *projectArgument = [self argumentNamed:@"--project"];
    BOOL installed = !projectArgument.length;
    NSURL *project = installed ? [[[NSBundle mainBundle] resourceURL] URLByAppendingPathComponent:@"tracker" isDirectory:YES]
                               : [NSURL fileURLWithPath:projectArgument isDirectory:YES];
    self.dataDirectory = installed ? [self applicationDataDirectory]
                                 : [project URLByAppendingPathComponent:@"data" isDirectory:YES];
    NSString *stateArgument = [self argumentNamed:@"--state-file"];
    self.stateURL = stateArgument ? [NSURL fileURLWithPath:stateArgument]
                                  : [self.dataDirectory URLByAppendingPathComponent:@"native_overlay_state.json"];

    NSRect screen = NSScreen.mainScreen.visibleFrame;
    NSSize size = NSMakeSize(408, MIN(760, screen.size.height - 42));
    NSPoint origin = NSMakePoint(NSMaxX(screen) - size.width - 16, NSMaxY(screen) - size.height - 24);
    self.panel = [[GameOverlayPanel alloc] initWithContentRect:NSMakeRect(origin.x, origin.y, size.width, size.height)
                                                      styleMask:(NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel)
                                                        backing:NSBackingStoreBuffered defer:NO];
    self.panel.hidesOnDeactivate = NO;
    self.panel.opaque = NO;
    self.panel.backgroundColor = NSColor.clearColor;
    self.panel.titleVisibility = NSWindowTitleHidden;
    self.panel.titlebarAppearsTransparent = YES;
    self.content = [[OverlayContentView alloc] initWithFrame:NSMakeRect(0, 0, size.width, size.height)];
    self.panel.contentView = self.content;
    [self applyAlwaysOnTop];
    [self installMenus];
    [self.panel orderFrontRegardless];

    [self launchBackendForProject:project];
    __weak typeof(self) weakSelf = self;
    self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) {
        [weakSelf pollState];
    }];
}

- (void)launchBackendForProject:(NSURL *)project {
    NSString *python = [self pythonExecutable];
    self.backend = [NSTask new];
    self.backend.executableURL = [NSURL fileURLWithPath:python];
    NSMutableArray<NSString *> *arguments = [@[ [project URLByAppendingPathComponent:@"main.py"].path, @"--native-feed", @"--state-file", self.stateURL.path ] mutableCopy];
    NSString *log = [self argumentNamed:@"--log"];
    if (log) [arguments addObjectsFromArray:@[@"--log", log]];
    self.backend.arguments = arguments;
    self.backend.currentDirectoryURL = project;
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    environment[@"OPEN_BATTLEGROUNDS_DATA_DIR"] = self.dataDirectory.path;
    self.backend.environment = environment;
    self.backend.standardOutput = [NSFileHandle fileHandleWithNullDevice];
    self.backend.standardError = [NSFileHandle fileHandleWithNullDevice];
    NSError *error = nil;
    if (![self.backend launchAndReturnError:&error]) [self.content renderWaiting];
}

- (void)pollState {
    NSData *data = [NSData dataWithContentsOfURL:self.stateURL];
    if (!data || [data isEqualToData:self.lastData]) return;
    NSError *error = nil;
    id object = [NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
    if (![object isKindOfClass:[NSDictionary class]]) return;
    self.lastData = data;
    [self.content renderFeed:object];
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    [self.pollTimer invalidate];
    if (self.backend.running) [self.backend terminate];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = NSApplication.sharedApplication;
        AppDelegate *delegate = [AppDelegate new];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
