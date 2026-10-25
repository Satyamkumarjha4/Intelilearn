"""The reviewed answer key of the seeded hero questions: question text -> the text of the one correct option.

Kept apart from the seed on purpose: the seed says what the page shows, this says what is true. A question or an answer
edited in the seed migration without the same review here fails `test_seed.py`.
"""

ANSWER_KEY = {
    "Which of these gives out light on its own?": "A burning candle",
    "What is 3/4 of 20?": "15",
    "In most languages, what does x = 5 do?": "Stores 5 in x",
    "Which planet is closest to the Sun?": "Mercury",
    "Which line divides Earth into the Northern and Southern Hemispheres?": "The Equator",
    "Burning fossil fuels adds mostly which greenhouse gas to the air?": "Carbon dioxide",
    "Which of these turns blue litmus paper red?": "Lemon juice",
    "Which data structure gives back items last-in, first-out?": "A stack",
    "When a good's price rises and people buy less of it, that shows the law of…": "Demand",
    "Which sentence is correct?": "She doesn't like tea.",
    "Compound interest means you earn interest on…": "Your deposit plus past interest",
    "Which part of a plant cell gives it a fixed shape?": "The cell wall",
    "A ball is thrown straight up. At the very top of its flight, its speed is…": "Zero",
    "What are the roots of x² − 5x + 6 = 0?": "2 and 3",
    "Which soil is best known for growing cotton in India?": "Black soil",
    "The revolt of 1857 began in which town?": "Meerut",
    "Inflation is 6% and your savings earn 4%. Your buying power…": "Falls by about 2%",
    "Adding a catalyst to a reaction changes…": "How fast equilibrium is reached",
    "What is the derivative of sin(x²)?": "2x cos(x²)",
    "Add 10 to every value in a data set. The standard deviation…": "Stays the same",
    "The Peace of Westphalia (1648) is often seen as the start of…": "The modern system of sovereign states",
    "Building a binary heap from n items, bottom-up, takes…": "O(n)",
    "A p-value of 0.03 means…": "Such data would be 3% likely if the null were true",
    "In long-run perfect competition, firms earn…": "Zero economic profit",
    "Which stage of cellular respiration makes most of the ATP?": "The electron transport chain",
}
