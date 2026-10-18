// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
#include "daicommand.h"

#include <QAction>
#include <QDir>
#include <QFile>
#include <QIcon>
#include <QJsonDocument>
#include <QJsonObject>
#include <QKeyEvent>
#include <QLocalSocket>
#include <QPainter>
#include <QPixmap>
#include <QProcess>

#include <sys/stat.h>

namespace {

constexpr qint64 kMaxFile = 4096;
constexpr int kMaxIdeas = 99;
constexpr int kHintMs = 12000;    // slow: a hint stays long enough to read, and nothing flickers

bool hebrewUi()
{
    const QString lang = qEnvironmentVariable("LC_ALL", qEnvironmentVariable("LC_MESSAGES", qEnvironmentVariable("LANG")));
    return lang.startsWith(QLatin1String("he"));
}

QString socketPath()
{
    // Same path as dai_command.ui.socket_path(); the directory is 0700.
    const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    return QDir(runtime).filePath(QStringLiteral("dai-command.sock"));
}

// "✦ 2" in the D.Ai cyan, for the idea chip inside the field.
QIcon ideaIcon(int ideas)
{
    QPixmap pixmap(44, 22);
    pixmap.fill(Qt::transparent);
    QPainter painter(&pixmap);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor(0x22, 0xD3, 0xEE, 60));
    painter.drawRoundedRect(QRectF(1, 2, 42, 18), 9, 9);
    painter.setPen(QColor(0x22, 0xD3, 0xEE));
    QFont font = painter.font();
    font.setBold(true);
    font.setPixelSize(12);
    painter.setFont(font);
    painter.drawText(QRectF(0, 2, 44, 18), Qt::AlignCenter, QStringLiteral("✦ %1").arg(ideas));
    return QIcon(pixmap);
}

bool startVoice()
{
    return QProcess::startDetached(QStringLiteral("dai-voice"),
                                   {QStringLiteral("toggle"), QStringLiteral("--to"), QStringLiteral("command")});
}

} // namespace

DaiCommandField::DaiCommandField(std::function<bool()> speak, QWidget *parent)
    : QLineEdit(parent)
    , mSpeak(speak ? std::move(speak) : std::function<bool()>(startVoice))
{
    const bool he = hebrewUi();
    setObjectName(QStringLiteral("DaiCommandField"));
    mPlaceholder = he ? QStringLiteral("הקלידו פקודה…") : QStringLiteral("Type a command…");
    setPlaceholderText(mPlaceholder);
    setAccessibleName(he ? QStringLiteral("שורת הפקודות של D.Ai") : QStringLiteral("D.Ai Command"));
    setToolTip(QStringLiteral("D.Ai Command (Super+Space)"));
    setClearButtonEnabled(false);
    setMinimumWidth(240);
    setMaximumWidth(340);

    mIdea = new QAction(this);
    mIdea->setObjectName(QStringLiteral("DaiIdeaChip"));
    connect(mIdea, &QAction::triggered, this, [this] { emit handOff(QString()); });  // empty: the suggestions
    addAction(mIdea, QLineEdit::LeadingPosition);
    mIdea->setVisible(false);

    const QIcon mic = QIcon::fromTheme(QStringLiteral("audio-input-microphone"),
                                       QIcon::fromTheme(QStringLiteral("microphone-sensitivity-high")));
    mMic = new QAction(mic, he ? QStringLiteral("דיבור (D.Ai Voice)") : QStringLiteral("Speak (D.Ai Voice)"), this);
    mMic->setObjectName(QStringLiteral("DaiMic"));
    mMic->setToolTip(mMic->text() + QStringLiteral(" · Super+Shift+Space"));
    connect(mMic, &QAction::triggered, this, [this] { mSpeak(); });
    addAction(mMic, QLineEdit::TrailingPosition);

    mHints = he ? QStringList{QStringLiteral("?  שאלו את Diamond: למה המחשב איטי?"),
                              QStringLiteral("+  תבנה לי אפליקציה לרשימת קניות"),
                              QStringLiteral("!  נעל את המסך אחרי 5 דקות"),
                              QStringLiteral("Super+Space פותח אותי מכל מקום")}
                : QStringList{QStringLiteral("?  Ask Diamond: why is it slow?"),
                              QStringLiteral("+  build me a shopping list app"),
                              QStringLiteral("!  lock the screen after 5 minutes"),
                              QStringLiteral("Super+Space opens me from anywhere")};
    mHintTimer.setInterval(kHintMs);
    connect(&mHintTimer, &QTimer::timeout, this, &DaiCommandField::nextHint);
    mHintTimer.start();

    connect(this, &QLineEdit::textEdited, this, [this](const QString &text) {
        if (!text.isEmpty())
            emit handOff(text);
    });
}

int DaiCommandField::ideasFromJson(const QByteArray &data)
{
    const QJsonDocument document = QJsonDocument::fromJson(data);
    if (!document.isObject())
        return 0;
    return qBound(0, document.object().value(QLatin1String("ideas")).toInt(0), kMaxIdeas);
}

void DaiCommandField::setIdeas(int ideas)
{
    ideas = qBound(0, ideas, kMaxIdeas);
    if (ideas != mDismissed)
        mDismissed = 0;  // a new idea comes back even after the last one was put away
    mIdeas = ideas;
    updateIdea();
}

bool DaiCommandField::ideaShown() const
{
    return mIdea->isVisible();
}

void DaiCommandField::dismissIdea()
{
    mDismissed = mIdeas;
    updateIdea();
}

void DaiCommandField::updateIdea()
{
    const bool show = mIdeas > 0 && mDismissed != mIdeas;
    if (show) {
        const bool he = hebrewUi();
        const QString text = he ? QStringLiteral("רעיונות מ־D.Ai: %1. ‏Enter לפתיחה, Delete להסתרה").arg(mIdeas)
                                : QStringLiteral("Ideas from D.Ai: %1. Enter opens them, Delete hides them").arg(mIdeas);
        mIdea->setIcon(ideaIcon(mIdeas));
        mIdea->setText(text);
        mIdea->setToolTip(text);
    }
    mIdea->setVisible(show);
    // The chip is also in the field's own description, for screen readers.
    setAccessibleDescription(show ? mIdea->text() : QString());
}

void DaiCommandField::nextHint()
{
    if (hasFocus() || !text().isEmpty())
        return;  // never change what someone may be reading or typing
    ++mHint;
    if (mHint >= mHints.size()) {
        setPlaceholderText(mPlaceholder);  // one round per login, then quiet
        mHintTimer.stop();
        return;
    }
    setPlaceholderText(mHints.at(mHint));
}

void DaiCommandField::keyPressEvent(QKeyEvent *event)
{
    if (event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter) {
        emit handOff(text());
        return;
    }
    if (event->key() == Qt::Key_Escape) {
        clear();
        clearFocus();
        return;
    }
    if (event->key() == Qt::Key_Delete && text().isEmpty() && ideaShown()) {
        dismissIdea();
        return;
    }
    QLineEdit::keyPressEvent(event);
}

void DaiCommandField::focusInEvent(QFocusEvent *event)
{
    setPlaceholderText(mPlaceholder);  // the plain words while it is in use
    QLineEdit::focusInEvent(event);
}

DaiCommandPlugin::DaiCommandPlugin(const ILXQtPanelPluginStartupInfo &startupInfo)
    : QObject()
    , ILXQtPanelPlugin(startupInfo)
{
    connect(&mField, &DaiCommandField::handOff, this, &DaiCommandPlugin::openCommand);
    const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    if (!runtime.isEmpty()) {
        mDirectory = QDir(runtime).filePath(QStringLiteral("dai"));
        ::mkdir(QFile::encodeName(mDirectory).constData(), 0700);
        mWatcher.addPath(mDirectory);
    }
    mSettle.setSingleShot(true);
    mSettle.setInterval(150);
    connect(&mWatcher, &QFileSystemWatcher::directoryChanged, &mSettle, qOverload<>(&QTimer::start));
    connect(&mSettle, &QTimer::timeout, this, &DaiCommandPlugin::reloadStatus);
    reloadStatus();
}

void DaiCommandPlugin::realign()
{
    mField.setFixedHeight(qMax(24, panel()->iconSize() + 10));
}

void DaiCommandPlugin::reloadStatus()
{
    if (mDirectory.isEmpty())
        return;
    QFile file(QDir(mDirectory).filePath(QStringLiteral("status.json")));
    QByteArray data;
    if (file.size() <= kMaxFile && file.open(QIODevice::ReadOnly))
        data = file.read(kMaxFile);
    mField.setIdeas(DaiCommandField::ideasFromJson(data));
}

void DaiCommandPlugin::openCommand(const QString &text)
{
    // Prefer the running instance (instant); otherwise start it with the text.
    QLocalSocket socket;
    socket.connectToServer(socketPath());
    if (socket.waitForConnected(200)) {
        socket.write(QByteArrayLiteral("query:") + text.toUtf8());
        socket.flush();
        socket.waitForBytesWritten(200);
        socket.disconnectFromServer();
    } else {
        QProcess::startDetached(QStringLiteral("dai-command"), {QStringLiteral("--query"), text});
    }
    mField.clear();
    mField.clearFocus();
}
