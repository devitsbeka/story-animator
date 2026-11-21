import React from "react";
import { Composition } from "remotion";
import { Film } from "./Film";
import { STORY } from "./story";
import { StyleSquare, StyleVertical } from "./StyleFrame";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Film" component={Film} width={STORY.width} height={STORY.height} fps={STORY.fps} durationInFrames={STORY.durationFrames} />
    <Composition id="StyleSquare" component={StyleSquare} width={1024} height={1024} fps={30} durationInFrames={90} />
    <Composition id="StyleVertical" component={StyleVertical} width={1080} height={1920} fps={30} durationInFrames={90} />
  </>
);
