import { IsString, MinLength } from "class-validator";

export class SendMessageDto {
  @IsString()
  @MinLength(2)
  content!: string;
}
