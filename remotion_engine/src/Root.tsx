import "./index.css";
import { Composition } from "remotion";
import { SocialProofReel, socialProofSchema } from "./SocialProofReel";

// Each <Composition> is an entry in the sidebar!

export const RemotionRoot: React.FC = () => {
  // We provide some dummy data so the user can preview the layout locally in the Studio.
  return (
    <>
      <Composition
        id="SocialProofReel"
        component={SocialProofReel}
        // If we have 3 reviews of 6 seconds each, duration is 18 seconds * 30 fps = 540 frames
        durationInFrames={540}
        fps={30}
        // Vertical 9:16 format (TikTok/Reels/Shorts)
        width={1080}
        height={1920}
        schema={socialProofSchema}
        defaultProps={{
          business_id: "preview_123",
          business_name: "Domestic Life / Electricista",
          overall_rating: 5,
          address: "Capitán Avalos 513d",
          place_id: "ChIJLxVIfT1q4AgRmrKyJ_ME5qk",
          status: "ready_for_render",
          // Background will just show dark gradient if not found locally, which is fine for preview
          background_local_path: "",
          reviews: [
            {
              reviewer_name: "Carlos Barría",
              review_text: "Llego una hora después que lo contacté listo para trabajar, Excelente trabajo, quedamos coordinamos para hacer algunos otros arreglos, recomiendo 100%",
              rating: 5,
              // Using a public URL to ensure the Avatar loads in local Studio preview
              avatar_url: "https://lh3.googleusercontent.com/a-/ALV-UjURw3aSfoLplH83c47z1FoZgD9eB8I65BxH1lIVwo81T8A_HvzfIQ=s128-c0x00000000-cc-rp-mo",
            },
            {
              reviewer_name: "Orlando Opazo",
              review_text: "1000% recomendado, excelente relación precio/trabajo.\nConoce mucho de instalaciones electricas.",
              rating: 5,
              avatar_url: "https://lh3.googleusercontent.com/a/ACg8ocKRVvsjFJ5ZMRUkLv9c0Vm0EmbVMiv3x26-yeVaIME9ulkqeQ=s128-c0x00000000-cc-rp-mo-ba2",
            },
            {
              reviewer_name: "true erudito",
              review_text: "Excelente trabajo muy profesional\nCosto ideal",
              rating: 5,
              avatar_url: "https://lh3.googleusercontent.com/a-/ALV-UjVQUiELL_dKNNas0Xl5q2uxfdWn8n5V7Swjh2VYGsPz0uuO-ttN=s128-c0x00000000-cc-rp-mo",
            }
          ]
        }}
      />
    </>
  );
};
