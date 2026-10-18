// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
#include <QDateTime>
#include <QSignalSpy>
#include <QTest>

#include "../daiclock.h"

class DaiClockTest : public QObject
{
    Q_OBJECT

private slots:
    void showsTheTimeAndOpensQuick()
    {
        qputenv("LANG", "en_US.UTF-8");
        int launched = 0;
        DaiClockButton clock([&launched] { ++launched; return true; });
        clock.refresh(QDateTime(QDate(2026, 10, 18), QTime(9, 5)));
        QCOMPARE(clock.text(), QStringLiteral("09:05"));
        QVERIFY(clock.toolTip().contains(QStringLiteral("2026")));
        QVERIFY(clock.toolTip().contains(QStringLiteral("D.Ai Quick")));
        QVERIFY(clock.accessibleName().startsWith(QStringLiteral("Clock, 09:05")));
        QTest::mouseClick(&clock, Qt::LeftButton);
        QCOMPARE(launched, 1);
    }

    void hebrew()
    {
        qputenv("LANG", "he_IL.UTF-8");
        DaiClockButton clock([] { return true; });
        clock.refresh(QDateTime(QDate(2026, 10, 18), QTime(14, 30)));
        QCOMPARE(clock.text(), QStringLiteral("14:30"));
        QVERIFY(clock.accessibleName().startsWith(QStringLiteral("שעון, 14:30")));
    }
};

QTEST_MAIN(DaiClockTest)
#include "test_daiclock.moc"
