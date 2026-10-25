import { AnimatePresence, motion } from "motion/react";
import {
  Circle, Coordinates, Ellipse, Line, Mafs, Plot, Point, Polygon, Polyline, Text, Theme, Transform, Vector,
  useMovablePoint, vec,
} from "mafs";
import "mafs/core.css";
import React, {
  Fragment, useCallback, useEffect, useId, useLayoutEffect, useMemo, useReducer, useRef, useState,
} from "react";

import { Assessment } from "./assessment";
import { Button, Callout, FormulaCard, KeyPoints, PageFrame, Section, Slider, WorkedExample } from "./blocks";
import { CodeBlock } from "./code";
import { Figure } from "./figure";
import { BlockMath, InlineMath, Markdown } from "./markdown";
import { LessonShell, withBoundary } from "./shell";

/** Everything generated code may refer to without defining it (the names in src/scope-names.mjs, plus `LESSON` and
 * `render`, which the runtime adds per document). */
export const SCOPE: Record<string, unknown> = {
  React, Fragment, useState, useEffect, useRef, useMemo, useCallback, useReducer, useLayoutEffect, useId,
  PageFrame, Section, Markdown, Callout, KeyPoints, WorkedExample, FormulaCard, CodeBlock, InlineMath, BlockMath,
  Figure, Button, Slider, Assessment, LessonShell, withBoundary,
  Mafs, Coordinates, Plot, Point, Line, Vector, Circle, Ellipse, Polygon, Polyline, Text, Theme, Transform,
  useMovablePoint, vec,
  motion, AnimatePresence,
};  // fmt: skip
