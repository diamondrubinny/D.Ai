// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// The Living Diamond against a real QToolButton named like LXQt's Start button.
#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QHBoxLayout>
#include <QTemporaryDir>
#include <QTest>
#include <QToolButton>

#include "../daistatus.h"

class DaiStatusTest : public QObject
{
    Q_OBJECT

private:
    QTemporaryDir mRuntime;

    void write(const QByteArray &json)
    {
        QDir().mkpath(mRuntime.filePath(QStringLiteral("dai")));
        QFile tmp(mRuntime.filePath(QStringLiteral("dai/.status.json.tmp")));
        QVERIFY(tmp.open(QIODevice::WriteOnly));
        tmp.write(json);
        tmp.close();
        // Replace like os.replace() does, so the directory watch fires.
        QFile::remove(mRuntime.filePath(QStringLiteral("dai/status.json")));
        QVERIFY(QFile::rename(tmp.fileName(), mRuntime.filePath(QStringLiteral("dai/status.json"))));
    }

private slots:
    void parsing()
    {
        QCOMPARE(DaiStatus::fromJson("{}").kind, DaiStatus::Kind::None);
        QCOMPARE(DaiStatus::fromJson("not json").kind, DaiStatus::Kind::None);
        QCOMPARE(DaiStatus::fromJson("{\"ideas\": 2}").kind, DaiStatus::Kind::Idea);
        QCOMPARE(DaiStatus::fromJson("{\"ideas\": 2, \"heal\": 1}").kind, DaiStatus::Kind::Heal);
        const DaiStatus all = DaiStatus::fromJson("{\"ideas\": 2, \"heal\": 1, \"privacy\": [\"Zoom\"]}");
        QCOMPARE(all.kind, DaiStatus::Kind::Privacy); // privacy first
        QCOMPARE(DaiStatus::fromJson("{\"heal\": 100000}").heal, 99);
        QCOMPARE(DaiStatus::fromJson("{\"heal\": -5}").kind, DaiStatus::Kind::None);
        const DaiStatus names = DaiStatus::fromJson(
            "{\"privacy\": [\"a\\u202eb\", \"\\u0007\", \"1\", \"2\", \"3\", \"4\", 5]}");
        QCOMPARE(names.recording, QStringList({QStringLiteral("ab"), QStringLiteral("1"), QStringLiteral("2")}));
        // MOM's guard: a busy app shows above an idea and below a problem.
        const DaiStatus busy = DaiStatus::fromJson("{\"ideas\": 1, \"busy\": [\"Game\\u202e\"]}");
        QCOMPARE(busy.kind, DaiStatus::Kind::Busy);
        QCOMPARE(busy.busy, QStringList({QStringLiteral("Game")}));
        QVERIFY(busy.describe(false).contains(QStringLiteral("Working very hard: Game")));
        QCOMPARE(DaiStatus::fromJson("{\"heal\": 1, \"busy\": [\"Game\"]}").kind, DaiStatus::Kind::Heal);
    }

    void decoratesTheStartButton()
    {
        QVERIFY(mRuntime.isValid());
        qputenv("XDG_RUNTIME_DIR", mRuntime.path().toUtf8());
        qputenv("LANG", "en_US.UTF-8");
        QWidget panel;
        QHBoxLayout layout(&panel);
        QToolButton start;
        start.setObjectName(QStringLiteral("FancyMenu"));
        start.setFixedSize(46, 44);
        start.setToolTip(QStringLiteral("Start menu"));
        layout.addWidget(&start);
        DaiStatusPlugin plugin({nullptr, nullptr, nullptr});
        layout.addWidget(plugin.widget());
        panel.show();
        QTest::qWait(50);

        auto badge = start.findChild<DaiStatusBadge *>();
        QVERIFY(badge);
        QVERIFY(!badge->isVisible());
        QCOMPARE(start.accessibleName(), QStringLiteral("Start"));
        QVERIFY(badge->testAttribute(Qt::WA_TransparentForMouseEvents)); // the menu still gets the clicks

        write("{\"heal\": 2}");
        QTRY_VERIFY_WITH_TIMEOUT(badge->isVisible(), 3000);
        QCOMPARE(start.accessibleName(), QStringLiteral("Start. D.Ai Heal found 2 problem(s). Help: Super+F1"));

        write("{\"heal\": 2, \"privacy\": [\"<b>Evil</b> & Co\"]}");
        QTRY_VERIFY_WITH_TIMEOUT(start.toolTip().contains(QStringLiteral("&lt;b&gt;Evil")), 3000);
        QVERIFY(!start.toolTip().contains(QStringLiteral("<b>")));

        write("{\"heal\": 0, \"privacy\": [], \"ideas\": 0}");
        QTRY_VERIFY_WITH_TIMEOUT(!badge->isVisible(), 3000);
        QCOMPARE(start.toolTip(), QStringLiteral("Start menu"));
        QCOMPARE(start.accessibleName(), QStringLiteral("Start"));

        QFile big(mRuntime.filePath(QStringLiteral("dai/status.json")));
        write(QByteArray("{\"heal\": 1, \"pad\": \"") + QByteArray(8000, 'x') + "\"}");
        QTest::qWait(400);
        QVERIFY(!badge->isVisible()); // larger than 4 KB: ignored
    }
};

QTEST_MAIN(DaiStatusTest)
#include "test_daistatus.moc"
