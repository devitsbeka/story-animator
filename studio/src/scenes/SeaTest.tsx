import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Ocean3D } from "../kit/ocean3d";
export const SeaTest: React.FC<{ debug?: string }> = ({ debug }) => {
  const f = useCurrentFrame();
  const t = f / 30;
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Ocean3D debug={debug} w={1080} h={1920} shot={{ time: t, cam: [-9, 3.2, 17], look: [0, 1.8, 0], fov: 42, roll: Math.sin(t * 0.6) * 2, moonDir: [0.42, 0.26, -0.86], seaState: 1.6, yacht: { x: 0, z: 0, heading: Math.PI / 2 + 0.25, lights: 1 } }} />
    </AbsoluteFill>
  );
};
