// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
#include "daistatus.h"

#include <QAccessible>
#include <QDir>
#include <QEvent>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QPainterPath>
#include <QRegularExpression>

#include <sys/stat.h>

namespace {

constexpr qint64 kMaxFile = 4096;
constexpr int kMaxCount = 99;
constexpr int kMaxApps = 3;
constexpr int kMaxName = 40;

bool hebrewUi()
{
    const QString lang = qEnvironmentVariable("LC_ALL", qEnvironmentVariable("LC_MESSAGES", qEnvironmentVariable("LANG")));
    return lang.startsWith(QLatin1String("he"));
}

int count(const QJsonObject &object, const char *key)
{
    return qBound(0, object.value(QLatin1String(key)).toInt(0), kMaxCount);
}

} // namespace

DaiStatus DaiStatus::fromJson(const QByteArray &data)
{
    DaiStatus status;
    const QJsonDocument document = QJsonDocument::fromJson(data);
    if (!document.isObject())
        return status;
    const QJsonObject object = document.object();
    status.heal = count(object, "heal");
    status.ideas = count(object, "ideas");
    // App names are shown to the user: plain text only, no control or bidi characters.
    static const QRegularExpression unsafe(QStringLiteral("[\\x00-\\x1f\\x7f\\x{200e}\\x{200f}\\x{202a}-\\x{202e}\\x{2066}-\\x{2069}]"));
    const auto names = [&](const char *key) {
        QStringList found;
        for (const QJsonValue &value : object.value(QLatin1String(key)).toArray()) {
            const QString name = value.toString().remove(unsafe).trimmed().left(kMaxName);
            if (!name.isEmpty() && found.size() < kMaxApps)
                found << name;
        }
        return found;
    };
    status.recording = names("privacy");
    status.busy = names("busy");
    if (!status.recording.isEmpty())
        status.kind = Kind::Privacy;
    else if (status.heal > 0)
        status.kind = Kind::Heal;
    else if (!status.busy.isEmpty())
        status.kind = Kind::Busy;
    else if (status.ideas > 0)
        status.kind = Kind::Idea;
    return status;
}

QString DaiStatus::describe(bool hebrew) const
{
    switch (kind) {
    case Kind::Privacy:
        return hebrew ? QStringLiteral("המיקרופון או המצלמה בשימוש: %1").arg(recording.join(QStringLiteral(", ")))
                      : QStringLiteral("Microphone or camera in use: %1").arg(recording.join(QStringLiteral(", ")));
    case Kind::Heal:
        return hebrew ? QStringLiteral("D.Ai Heal מצא תקלות (%1). לעזרה: Super+F1").arg(heal)
                      : QStringLiteral("D.Ai Heal found %1 problem(s). Help: Super+F1").arg(heal);
    case Kind::Busy:
        return hebrew ? QStringLiteral("עובד קשה מאוד: %1. לפרטים: Ctrl+Shift+Esc").arg(busy.join(QStringLiteral(", ")))
                      : QStringLiteral("Working very hard: %1. Details: Ctrl+Shift+Esc").arg(busy.join(QStringLiteral(", ")));
    case Kind::Idea:
        return hebrew ? QStringLiteral("ל־D.Ai יש רעיון בשבילך. Super+Space")
                      : QStringLiteral("D.Ai has an idea for you. Super+Space");
    case Kind::None:
        break;
    }
    return QString();
}

DaiStatusBadge::DaiStatusBadge(QToolButton *start)
    : QWidget(start)
{
    setObjectName(QStringLiteral("DaiStatusBadge"));
    setAttribute(Qt::WA_TransparentForMouseEvents); // clicks still open the Start menu
    setAttribute(Qt::WA_NoSystemBackground);
    setGeometry(start->rect());
    start->installEventFilter(this);
    hide();
}

void DaiStatusBadge::setStatus(const DaiStatus &status)
{
    mStatus = status;
    setVisible(status.kind != DaiStatus::Kind::None);
    raise();
    update();
}

bool DaiStatusBadge::eventFilter(QObject *watched, QEvent *event)
{
    if (watched == parentWidget() && event->type() == QEvent::Resize)
        setGeometry(parentWidget()->rect());
    return QWidget::eventFilter(watched, event);
}

void DaiStatusBadge::paintEvent(QPaintEvent *)
{
    // Shape as well as colour (WCAG 1.4.1): circle = recording, triangle = problem, square = an app runs away,
    // diamond = idea.
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    const qreal size = 11.0;
    const qreal inset = 5.0;
    const bool rtl = parentWidget()->layoutDirection() == Qt::RightToLeft;
    const QPointF center(rtl ? inset + size / 2 : width() - inset - size / 2, inset + size / 2);
    const QRectF box(center.x() - size / 2, center.y() - size / 2, size, size);
    QPainterPath shape;
    QColor color;
    switch (mStatus.kind) {
    case DaiStatus::Kind::Privacy:
        shape.addEllipse(box);
        color = QColor(0xF8, 0x71, 0x71);
        break;
    case DaiStatus::Kind::Heal:
        shape.moveTo(box.center().x(), box.top());
        shape.lineTo(box.right(), box.bottom());
        shape.lineTo(box.left(), box.bottom());
        shape.closeSubpath();
        color = QColor(0xFB, 0xBF, 0x24);
        break;
    case DaiStatus::Kind::Busy:
        shape.addRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 2.0, 2.0);
        color = QColor(0xFB, 0x92, 0x3C);
        break;
    case DaiStatus::Kind::Idea:
        shape.moveTo(box.center().x(), box.top());
        shape.lineTo(box.right(), box.center().y());
        shape.lineTo(box.center().x(), box.bottom());
        shape.lineTo(box.left(), box.center().y());
        shape.closeSubpath();
        color = QColor(0x22, 0xD3, 0xEE);
        break;
    case DaiStatus::Kind::None:
        return;
    }
    painter.setPen(QPen(QColor(0x0B, 0x10, 0x20), 2.0)); // a dark outline keeps it visible on any background
    painter.setBrush(color);
    painter.drawPath(shape);
}

DaiStatusPlugin::DaiStatusPlugin(const ILXQtPanelPluginStartupInfo &startupInfo)
    : QObject()
    , ILXQtPanelPlugin(startupInfo)
{
    mAnchor.setObjectName(QStringLiteral("DaiStatusAnchor"));
    mAnchor.setFixedSize(0, 0);
    const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    if (!runtime.isEmpty()) {
        mDirectory = QDir(runtime).filePath(QStringLiteral("dai"));
        ::mkdir(QFile::encodeName(mDirectory).constData(), 0700); // the writers create it 0700 too
        mWatcher.addPath(mDirectory);
    }
    // os.replace() renames into the directory, so watch the directory; settle bursts of events.
    mSettle.setSingleShot(true);
    mSettle.setInterval(150);
    connect(&mWatcher, &QFileSystemWatcher::directoryChanged, &mSettle, qOverload<>(&QTimer::start));
    connect(&mSettle, &QTimer::timeout, this, &DaiStatusPlugin::reload);
    QTimer::singleShot(0, this, &DaiStatusPlugin::attach);
}

void DaiStatusPlugin::realign()
{
    attach();
}

void DaiStatusPlugin::attach()
{
    if (mStart)
        return;
    QWidget *panelWindow = mAnchor.window();
    if (!panelWindow || panelWindow == &mAnchor)
        return;
    mStart = panelWindow->findChild<QToolButton *>(QStringLiteral("FancyMenu"));
    if (!mStart)
        return;
    mStartName = mStart->accessibleName().isEmpty() ? (hebrewUi() ? QStringLiteral("התחל") : QStringLiteral("Start"))
                                                     : mStart->accessibleName();
    mStartTip = mStart->toolTip();
    mBadge = new DaiStatusBadge(mStart);
    reload();
}

void DaiStatusPlugin::reload()
{
    if (!mStart || !mBadge)
        return;
    QByteArray data;
    QFile file(QDir(mDirectory).filePath(QStringLiteral("status.json")));
    if (!mDirectory.isEmpty() && file.size() <= kMaxFile && file.open(QIODevice::ReadOnly))
        data = file.read(kMaxFile);
    const DaiStatus status = DaiStatus::fromJson(data);
    mBadge->setStatus(status);

    const QString text = status.describe(hebrewUi());
    const QString name = text.isEmpty() ? mStartName : mStartName + QStringLiteral(". ") + text;
    if (mStart->accessibleName() != name) {
        mStart->setAccessibleName(name);
        QAccessibleEvent changed(mStart, QAccessible::NameChanged);
        QAccessible::updateAccessibility(&changed);
    }
    // Always rich text with escaped content, so an app name can never be read as markup.
    mStart->setToolTip(text.isEmpty() ? mStartTip
                                      : QStringLiteral("<qt>%1</qt>").arg(text.toHtmlEscaped()));
}
