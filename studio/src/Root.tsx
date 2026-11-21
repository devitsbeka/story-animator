import React from "react";
import { Composition } from "remotion";
import { Study916, StudySquare } from "./scenes/Study";
import { SentinelFilm } from "./episodes/sentinel/Film";
import { DURATION } from "./episodes/sentinel/cues";
import { HeroSheet } from "./scenes/HeroSheet";
import { SeaTest } from "./scenes/SeaTest";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Sentinel" component={SentinelFilm} width={1080} height={1920} fps={30} durationInFrames={DURATION} />
    <Composition id="SeaTest" component={SeaTest} width={1080} height={1920} fps={30} durationInFrames={120} />
    <Composition id="HeroSheet" component={HeroSheet} width={1920} height={1080} fps={30} durationInFrames={1} />
    <Composition id="StudySquare" component={StudySquare} width={1024} height={1024} fps={30} durationInFrames={1} />
    <Composition id="Study916" component={Study916} width={1080} height={1920} fps={30} durationInFrames={150} />
  </>
);
