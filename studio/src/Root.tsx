import React from "react";
import { Composition } from "remotion";
import { Study916, StudySquare } from "./scenes/Study";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="StudySquare" component={StudySquare} width={1024} height={1024} fps={30} durationInFrames={1} />
    <Composition id="Study916" component={Study916} width={1080} height={1920} fps={30} durationInFrames={150} />
  </>
);
