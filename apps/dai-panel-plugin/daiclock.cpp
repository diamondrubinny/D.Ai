// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
#include "daiclock.h"

#include <QDateTime>
#include <QLocale>
#include <QProcess>

namespace {

bool hebrewUi()
{
    const QString lang = qEnvironmentVariable("LC_ALL", qEnvironmentVariable("LC_MESSAGES", qEnvironmentVariable("LANG")));
    return lang.startsWith(QLatin1String("he"));
}

bool launchQuick()
{
    return QProcess::startDetached(QStringLiteral("dai-quick"), {});
}

} // namespace

DaiClockButton::DaiClockButton(std::function<bool()> launch, QWidget *parent)
    : QToolButton(parent)
    , mLaunch(launch ? std::move(launch) : std::function<bool()>(launchQuick))
{
    setObjectName(QStringLiteral("DaiClock"));
    setAutoRaise(true);
    setToolButtonStyle(Qt::ToolButtonTextOnly);
    connect(this, &QToolButton::clicked, this, [this] { mLaunch(); });
    mTimer.setSingleShot(true);
    mTimer.setTimerType(Qt::PreciseTimer);
    connect(&mTimer, &QTimer::timeout, this, [this] {
        refresh(QDateTime::currentDateTime());
        schedule();
    });
    refresh(QDateTime::currentDateTime());
    schedule();
}

void DaiClockButton::refresh(const QDateTime &now)
{
    const QLocale locale;
    const QString time = locale.toString(now.time(), QStringLiteral("HH:mm"));
    const QString date = locale.toString(now.date(), QLocale::LongFormat);
    setText(time);
    const QString open = hebrewUi() ? QStringLiteral("לחיצה או Super+N: ‏D.Ai Quick") : QStringLiteral("Click or Super+N: D.Ai Quick");
    setToolTip(date + QStringLiteral("\n") + open);
    setAccessibleName((hebrewUi() ? QStringLiteral("שעון, %1, %2. פותח את D.Ai Quick")
                                  : QStringLiteral("Clock, %1, %2. Opens D.Ai Quick")).arg(time, date));
}

void DaiClockButton::schedule()
{
    // Wake on the next minute (plus a little), not every second.
    const QTime now = QTime::currentTime();
    const int msToNextMinute = (60 - now.second()) * 1000 - now.msec() + 50;
    mTimer.start(msToNextMinute);
}

DaiClockPlugin::DaiClockPlugin(const ILXQtPanelPluginStartupInfo &startupInfo)
    : QObject()
    , ILXQtPanelPlugin(startupInfo)
{
}
