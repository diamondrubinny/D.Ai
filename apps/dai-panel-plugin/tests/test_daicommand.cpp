// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
#include <QAction>
#include <QSignalSpy>
#include <QTest>

#include "../daicommand.h"

class DaiCommandTest : public QObject
{
    Q_OBJECT

private slots:
    void ideaChipComesAndGoes()
    {
        qputenv("LANG", "en_US.UTF-8");
        DaiCommandField field([] { return true; });
        field.show();
        QVERIFY(!field.ideaShown());
        field.setIdeas(DaiCommandField::ideasFromJson(R"({"ideas": 2, "heal": 1})"));
        QVERIFY(field.ideaShown());
        QVERIFY(field.accessibleDescription().contains(QStringLiteral("Ideas from D.Ai: 2")));
        QSignalSpy handed(&field, &DaiCommandField::handOff);
        field.findChild<QAction *>(QStringLiteral("DaiIdeaChip"))->trigger();
        QCOMPARE(handed.count(), 1);
        QCOMPARE(handed.first().first().toString(), QString());  // empty: D.Ai Command shows the suggestions
        field.setFocus();
        QTest::keyClick(&field, Qt::Key_Delete);
        QVERIFY(!field.ideaShown());
        field.setIdeas(2);
        QVERIFY(!field.ideaShown());  // the same ideas stay put away
        field.setIdeas(3);
        QVERIFY(field.ideaShown());   // a new one comes back
    }

    void badStatusIsNoIdea()
    {
        QCOMPARE(DaiCommandField::ideasFromJson("not json"), 0);
        QCOMPARE(DaiCommandField::ideasFromJson(R"({"ideas": -4})"), 0);
        QCOMPARE(DaiCommandField::ideasFromJson(R"({"ideas": 100000})"), 99);
    }

    void micStartsVoice()
    {
        int spoken = 0;
        DaiCommandField field([&spoken] { ++spoken; return true; });
        field.findChild<QAction *>(QStringLiteral("DaiMic"))->trigger();
        QCOMPARE(spoken, 1);
    }

    void hintsOneRoundAndNeverWhileTyping()
    {
        qputenv("LANG", "he_IL.UTF-8");
        DaiCommandField field([] { return true; });
        const QString plain = field.placeholderText();
        QCOMPARE(plain, QStringLiteral("הקלידו פקודה…"));
        field.nextHint();
        QCOMPARE(field.placeholderText(), field.hints().first());
        field.setText(QStringLiteral("x"));
        field.nextHint();
        QCOMPARE(field.placeholderText(), field.hints().first());  // someone is typing: unchanged
        field.clear();
        for (int i = 0; i < field.hints().size(); ++i)
            field.nextHint();
        QCOMPARE(field.placeholderText(), plain);  // one round, then the plain words
        field.nextHint();
        QCOMPARE(field.placeholderText(), plain);
    }
};

QTEST_MAIN(DaiCommandTest)
#include "test_daicommand.moc"
