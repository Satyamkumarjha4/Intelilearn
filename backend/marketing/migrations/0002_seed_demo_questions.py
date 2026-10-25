"""Seeds the 25 questions the landing page's try-it card starts with.

Self-contained on purpose (a migration must keep working when the app's code changes). Each question is a row of
(subject, who it is pitched at, band, question, three options, index of the right one, where the lesson would begin after
a right answer, and after a wrong one or "I don't know"). The level a learner is placed at follows from the band:

    band      1 Basics   2 Easy   3 Medium   4 Hard   5 Expert
    right ->  level 2    3        3          4        5
    wrong ->  level 1    1        2          2        3

The answers are reviewed in tests/support/answer_key.py, which tests/marketing/test_seed.py holds this file to.
"""

from django.db import DEFAULT_DB_ALIAS, migrations

RIGHT_LEVEL = {1: 2, 2: 3, 3: 3, 4: 4, 5: 5}
WRONG_LEVEL = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}
LEVEL_LABEL = {1: "New to it", 2: "Building up", 3: "Getting there", 4: "Confident", 5: "Expert"}

# fmt: off
QUESTIONS = [
    ("Physics", "Class 6", 1, "Which of these gives out light on its own?",
     ["The Moon", "A burning candle", "A mirror"], 1,
     "How light travels in straight lines, and why that makes shadows.",
     "What makes something give out light, and what only bounces it back."),
    ("Maths", "Class 6", 1, "What is 3/4 of 20?",
     ["12", "15", "5"], 1,
     "Adding and comparing fractions that have different bottoms.",
     "What a fraction of a number means, using slices you can picture."),
    ("Computer science", "Class 8", 1, "In most languages, what does x = 5 do?",
     ["Checks if x is 5", "Stores 5 in x", "Adds 5 to x"], 1,
     "How a program remembers things in variables, and how they change as it runs.",
     "What a variable is, using a labelled box that holds a value."),
    ("General science", "Class 6", 1, "Which planet is closest to the Sun?",
     ["Venus", "Mercury", "Mars"], 1,
     "Why the planets orbit the Sun at different distances and speeds.",
     "What the Solar System is, and the order of the planets from the Sun."),
    ("Geography", "Class 6", 1, "Which line divides Earth into the Northern and Southern Hemispheres?",
     ["The Equator", "The Prime Meridian", "The Tropic of Cancer"], 0,
     "How latitudes and longitudes work together to find any place on a map.",
     "What latitudes are, and why the Equator is the line the rest are measured from."),
    ("Environmental science", "Class 8", 1, "Burning fossil fuels adds mostly which greenhouse gas to the air?",
     ["Carbon dioxide", "Oxygen", "Helium"], 0,
     "How greenhouse gases trap heat, and why more of them warms the planet.",
     "What the greenhouse effect is, and why we need some of it."),
    ("Chemistry", "Class 7", 2, "Which of these turns blue litmus paper red?",
     ["Lemon juice", "Soap solution", "Baking soda solution"], 0,
     "What happens when an acid meets a base, and why the result is neutral.",
     "What acids and bases are, and how indicators like litmus show them."),
    ("Computer science", "College", 2, "Which data structure gives back items last-in, first-out?",
     ["A queue", "A stack", "A linked list"], 1,
     "How a stack powers undo buttons and function calls, and how a queue differs.",
     "What a data structure is, and how adding and removing items works in a stack."),
    ("Economics", "Class 11", 2, "When a good's price rises and people buy less of it, that shows the law of…",
     ["Demand", "Supply", "Diminishing returns"], 0,
     "What shifts the whole demand curve, as opposed to moving along it.",
     "What demand means, and why price and quantity bought move in opposite directions."),
    ("English grammar", "Class 7", 2, "Which sentence is correct?",
     ["She don't like tea.", "She doesn't like tea.", "She not likes tea."], 1,
     "How subjects and verbs agree, including tricky ones like \"everyone\" and \"neither\".",
     "How to make a sentence negative with do, does and did."),
    ("Personal finance", "Working", 2, "Compound interest means you earn interest on…",
     ["Only your first deposit", "Your deposit plus past interest", "Only the interest earned"], 1,
     "How the rule of 72 shows how long money takes to double.",
     "How interest builds on interest, and why starting early matters so much."),
    ("Biology", "Class 8", 2, "Which part of a plant cell gives it a fixed shape?",
     ["The cell wall", "The nucleus", "Mitochondria"], 0,
     "How plant and animal cells differ, and why plant cells do not burst in water.",
     "What the parts of a cell do, starting with the ones plants have and animals don't."),
    ("Physics", "Class 9", 3, "A ball is thrown straight up. At the very top of its flight, its speed is…",
     ["Zero", "At its fastest", "The same as when it was thrown"], 0,
     "Why the ball slows down on the way up, and what happens to its energy at the top.",
     "What speed and velocity mean when something moves up and comes back down."),
    ("Maths", "Class 10", 3, "What are the roots of x² − 5x + 6 = 0?",
     ["1 and 6", "2 and 3", "−2 and −3"], 1,
     "Why the discriminant tells you how many roots a quadratic has, before you solve it.",
     "Solving quadratics by factorising: splitting the middle term, step by step."),
    ("Geography", "Class 10", 3, "Which soil is best known for growing cotton in India?",
     ["Black soil", "Laterite soil", "Desert soil"], 0,
     "How climate and rock shape India's soils, and which crops each one suits.",
     "What soil is made of, and the main soil types found across India."),
    ("History", "Class 8", 3, "The revolt of 1857 began in which town?",
     ["Plassey", "Meerut", "Lucknow"], 1,
     "Why the revolt spread so fast, and what changed in British rule afterwards.",
     "What life under Company rule was like, and the grievances that built up before 1857."),
    ("Personal finance", "Working", 3, "Inflation is 6% and your savings earn 4%. Your buying power…",
     ["Grows by 2%", "Falls by about 2%", "Stays the same"], 1,
     "Real versus nominal returns, and where to look for returns that beat inflation.",
     "What inflation is, and why prices creep up while savings sit still."),
    ("Chemistry", "Class 12", 4, "Adding a catalyst to a reaction changes…",
     ["How fast equilibrium is reached", "The amount of product at equilibrium", "The heat the reaction releases"], 0,
     "How a catalyst lowers the energy barrier, and why equilibrium itself stays put.",
     "What activation energy is, and what controls how fast a reaction goes."),
    ("Maths", "Class 12", 4, "What is the derivative of sin(x²)?",
     ["cos(x²)", "2x cos(x²)", "2x sin(x²)"], 1,
     "The chain rule on harder composites, and where it hides in implicit differentiation.",
     "What the chain rule says, using an outer function and an inner one."),
    ("Statistics", "College", 4, "Add 10 to every value in a data set. The standard deviation…",
     ["Goes up by 10", "Stays the same", "Doubles"], 1,
     "What spread measures, and how scaling data (not shifting it) changes it.",
     "What standard deviation measures, and how it differs from the mean."),
    ("History", "Class 12", 4, "The Peace of Westphalia (1648) is often seen as the start of…",
     ["The modern system of sovereign states", "The Protestant Reformation", "The Industrial Revolution"], 0,
     "How sovereignty became the rule between states, and where nationalism comes in.",
     "What the Thirty Years' War was about, and why Europe needed a peace like this."),
    ("Computer science", "College", 5, "Building a binary heap from n items, bottom-up, takes…",
     ["O(n)", "O(n log n)", "O(log n)"], 0,
     "Why heapify is linear, and how that makes heapsort and priority queues fast.",
     "How a heap keeps its smallest item on top, and how items sift up and down."),
    ("Statistics", "College", 5, "A p-value of 0.03 means…",
     ["The null is 3% likely to be true", "Such data would be 3% likely if the null were true",
      "The effect is 97% likely to be real"], 1,
     "Why p-values are so often misread, and what effect sizes and intervals add.",
     "What a hypothesis test asks, and how a p-value answers it."),
    ("Economics", "College", 5, "In long-run perfect competition, firms earn…",
     ["Zero economic profit", "The maximum possible profit", "A fixed loss"], 0,
     "How entry and exit push price down to the lowest average cost, and how monopolies break that.",
     "What perfect competition assumes, and what profit means to an economist."),
    ("Biology", "College", 5, "Which stage of cellular respiration makes most of the ATP?",
     ["Glycolysis", "The Krebs cycle", "The electron transport chain"], 2,
     "How the proton gradient drives ATP synthase, and what happens when it leaks.",
     "How a cell turns glucose into ATP, one stage at a time."),
]
# fmt: on


def _outcome(level: int, lesson_start: str) -> dict:
    return {"level": level, "level_label": LEVEL_LABEL[level], "lesson_start": lesson_start}


def _alias(schema_editor) -> str:
    return schema_editor.connection.alias if schema_editor else DEFAULT_DB_ALIAS


def seed(apps, schema_editor):
    DemoQuestion = apps.get_model("marketing", "DemoQuestion")
    questions = DemoQuestion.objects.using(_alias(schema_editor))
    for subject, level_label, band, question, options, correct, right_start, wrong_start in QUESTIONS:
        questions.get_or_create(
            question=question,
            defaults={
                "subject": subject,
                "level_label": level_label,
                "band": band,
                "options": options,
                "correct_index": correct,
                "outcome_right": _outcome(RIGHT_LEVEL[band], right_start),
                "outcome_wrong": _outcome(WRONG_LEVEL[band], wrong_start),
                "is_active": True,
            },
        )


def unseed(apps, schema_editor):
    """Undoing removes only the seeded questions, never ones added since."""
    DemoQuestion = apps.get_model("marketing", "DemoQuestion")
    DemoQuestion.objects.using(_alias(schema_editor)).filter(question__in=[row[3] for row in QUESTIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("marketing", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
